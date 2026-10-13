"""三角洲数据帝数据源（真实线上接口）。

接口约定（完整字段与调研过程见 `docs/api_spec.md`）：

* Base URL：`https://orzice.com/workApi`
* 鉴权：查询参数 `token`，不是 Header
* 响应信封：`{code, msg/message, data}`，`code = 0` 为成功
* 计费：`item_info_all` / `item_price_all` 各约 20 次资源；
  `manufacture` / `manufacturePro` 各 1 次资源
* 未开通服务或 Token 错误：HTTP 404（这很容易被误当成"接口不存在"而疯狂重试，故单列）

异常映射到 `base.py` 的异常体系后，重试策略由上层（Collector）统一决定，
本模块只负责"把 HTTP 世界翻译成干净的 Python 对象"。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.data_sources.base import (
    STATION_KEYS,
    DataSource,
    DataSourceAuthError,
    DataSourceRateLimitError,
    DataSourceResponseError,
    DataSourceUnavailableError,
    ItemRecord,
    ManufactureRecord,
    PriceRecord,
)

# 数据帝的 Token 只能用查询串传（`?token=...`），而 httpx 默认会把**完整 URL**
# 记进 INFO 日志——密钥就会明文写进日志文件或控制台。
# 在这里（唯一发起请求的模块）压掉，服务进程、命令行脚本、定时任务全都覆盖到。
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DEFAULT_BASE_URL = "https://orzice.com/workApi"
USER_AGENT = "DeltaForceApi/1.0"
DEFAULT_TIMEOUT = 10.0


class DeltaDataSource(DataSource):
    """通过 HTTP 调用三角洲数据帝的线上接口。"""

    name = "delta"

    def __init__(
        self,
        *,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        if not token or not token.strip():
            raise DataSourceAuthError("缺少 DELTA_API_TOKEN，无法使用真实数据源")

        self._token = token.strip()
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------ #
    # 物品基础信息
    # ------------------------------------------------------------------ #
    def fetch_items(self) -> list[ItemRecord]:
        payload = self._get("/v1/sjz_api/item_info_all")
        records: list[ItemRecord] = []
        for row in self._rows(payload):
            oid = _as_int(row.get("oid"))
            if not oid:
                # 不可交易物品的 oid 为 0，无法与价格接口对应，跳过
                continue
            records.append(
                ItemRecord(
                    external_id=str(oid),
                    name=_as_text(row.get("objectName")) or f"未知物品 {oid}",
                    primary_class=_as_text(row.get("primaryClass")),
                    # ⚠️ 这两个字段的内容与文档写的正好相反（实测确认）：
                    # `secondClassCN` 放的是代码（accBarrel），
                    # `secondClass` 放的才是中文名（枪管）。
                    second_class=_as_text(row.get("secondClassCN")),
                    second_class_cn=_as_text(row.get("secondClass")),
                    grade=_as_int(row.get("grade")),
                    pic_url=_as_text(row.get("pic")),
                    is_tradable=_as_int(row.get("is_get")) == 1,
                    object_id=_as_text(row.get("objectID")),
                    slot_w=_as_int(row.get("width")),
                    slot_h=_as_int(row.get("length")),
                )
            )

        if not records:
            raise DataSourceResponseError("item_info_all 没有返回任何可交易物品")
        return records

    # ------------------------------------------------------------------ #
    # 最新价格
    # ------------------------------------------------------------------ #
    def fetch_prices(self) -> list[PriceRecord]:
        payload = self._get("/v1/sjz_api/item_price_all", {"isZb": 0})
        records: list[PriceRecord] = []
        for row in self._rows(payload):
            item_id = _as_int(row.get("id"))
            if not item_id:
                continue
            records.append(
                PriceRecord(
                    external_id=str(item_id),
                    price=_as_int(row.get("price")),
                    price_start=_as_int(row.get("price_start")),
                    bl_today=_as_float(row.get("bl")),
                    day_3_price=_as_int(row.get("day_3_price")),
                    day_3_bl=_as_float(row.get("day_3_bl")),
                    day_7_price=_as_int(row.get("day_7_price")),
                    day_7_bl=_as_float(row.get("day_7_bl")),
                    day_30_price=_as_int(row.get("day_30_price")),
                    day_30_bl=_as_float(row.get("day_30_bl")),
                    source_updated_at=_from_unix(row.get("is_get_time")),
                    raw=dict(row),
                )
            )

        if not records:
            raise DataSourceResponseError("item_price_all 没有返回任何价格")
        return records

    # ------------------------------------------------------------------ #
    # 特勤处制造
    # ------------------------------------------------------------------ #
    def fetch_manufacture(self, station_id: int, level: int) -> list[ManufactureRecord]:
        """自有源计算的制造收益（接口 `manufacturePro`，1 次资源/请求）。"""
        payload = self._get(
            "/v1/sjz_api/manufacturePro",
            {"t": station_id, "l": level},
        )
        station = STATION_KEYS.get(station_id, str(station_id))
        return [
            self._to_manufacture(row, station, level, "pro")
            for row in self._rows(payload)
        ]

    def fetch_manufacture_official(self, station_id: int) -> list[ManufactureRecord]:
        """官方口径的制造利润（接口 `manufacture`，文档自述"不准"）。

        用于与 Pro 数据交叉校验；官方接口不区分部门等级，等级记为 0。
        """
        payload = self._get("/v1/sjz_api/manufacture", {"t": station_id})
        station = STATION_KEYS.get(station_id, str(station_id))
        return [
            self._to_manufacture(row, station, 0, "official")
            for row in self._rows(payload)
        ]

    # ------------------------------------------------------------------ #
    # HTTP 细节
    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        query["token"] = self._token

        try:
            # UA 显式写在每次请求上：注入外部 client 时也能保持一致，
            # 不依赖 client 自己的默认 header
            response = self._client.get(
                f"{self._base_url}{path}",
                params=query,
                headers={"User-Agent": USER_AGENT},
            )
        except httpx.TimeoutException as exc:
            raise DataSourceUnavailableError(f"请求超时：{path}") from exc
        except httpx.TransportError as exc:
            raise DataSourceUnavailableError(f"网络错误：{path}（{exc}）") from exc

        status = response.status_code
        if status == 404:
            raise DataSourceAuthError(
                "无权限访问：请检查 DELTA_API_TOKEN，以及对应接口是否已在控制台开通"
            )
        if status == 429:
            raise DataSourceRateLimitError("请求被限流", retry_after=_retry_after(response))
        if status >= 500:
            raise DataSourceUnavailableError(f"服务端错误 HTTP {status}：{path}")
        if status >= 400:
            raise DataSourceResponseError(f"请求失败 HTTP {status}：{path}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise DataSourceResponseError(f"响应不是合法 JSON：{path}") from exc
        if not isinstance(payload, dict):
            raise DataSourceResponseError(f"响应结构不符合预期：{path}")

        code = payload.get("code")
        if code not in (0, None):
            message = payload.get("msg") or payload.get("message") or "未知错误"
            raise DataSourceResponseError(f"接口业务错误 code={code}：{message}")
        return payload

    @staticmethod
    def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return []

    def _to_manufacture(
        self,
        row: dict[str, Any],
        station: str,
        level: int,
        origin: str,
    ) -> ManufactureRecord:
        period = _as_float(row.get("period"))
        profit = _as_int(row.get("price"))
        per_hour = _as_int(row.get("price_hour"))
        if per_hour is None and profit is not None and period:
            per_hour = round(profit / period)

        return ManufactureRecord(
            item_key=str(row.get("objectID") or row.get("id") or ""),
            name=_as_text(row.get("name")) or "未知物品",
            station=station,
            unlock_level=level,
            period_hours=period,
            market_price=_as_int(row.get("priceMax")),
            fee=_as_int(row.get("sxf")),
            profit=profit,
            profit_per_hour=per_hour,
            grade=_as_int(row.get("grade")),
            primary_class=_as_text(row.get("primaryClass")),
            second_class_cn=_as_text(row.get("secondClassCN")),
            pic_url=_as_text(row.get("pic")),
            is_get=_as_int(row.get("isGet")) != 0,
            is_pay=_as_int(row.get("is_pay")) != 0,
            origin=origin,
            raw=dict(row),
        )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _from_unix(value: Any) -> datetime | None:
    """把接口的 Unix 时间戳（`is_get_time`）转成库内约定的 naive UTC。"""
    seconds = _as_int(value)
    if not seconds:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
