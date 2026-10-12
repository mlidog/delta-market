"""数据源接口与数据结构定义。

本模块刻意**不依赖 SQLAlchemy，也不依赖 FastAPI**：数据源只负责"把外部世界翻译成
干净的 Python 对象"，落库与对外接口是上层的事。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self


# --------------------------------------------------------------------------- #
# 异常体系：M3 的重试策略依据 `retryable` 决定是否重试
# --------------------------------------------------------------------------- #
class DataSourceError(RuntimeError):
    """数据源错误基类。"""

    retryable = False


class DataSourceUnavailableError(DataSourceError):
    """网络异常、超时、服务端 5xx —— 可重试。"""

    retryable = True


class DataSourceRateLimitError(DataSourceUnavailableError):
    """被限流（HTTP 429）—— 可重试，且优先遵守服务端给出的 Retry-After。"""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class DataSourceAuthError(DataSourceError):
    """Token 无效、无权限 —— 重试没有意义。

    数据帝对"未开通服务 / Token 错误"统一返回 HTTP 404，也归入此类。
    """


class DataSourceResponseError(DataSourceError):
    """响应结构不符合预期或业务错误码非 0 —— 重试同样无意义。"""


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ItemRecord:
    """物品基础信息。

    `external_id` 是数据源侧的物品主键；对数据帝来说就是第三代数据 ID（`oid`）。
    """

    external_id: str
    name: str
    primary_class: str | None = None
    second_class: str | None = None
    second_class_cn: str | None = None
    grade: int | None = None
    pic_url: str | None = None
    is_tradable: bool = True
    #: 三角洲官方小程序 ID（数据帝字段 `objectID`），仅作对照
    object_id: str | None = None
    slot_w: int | None = None
    slot_h: int | None = None

    @property
    def slot_area(self) -> int | None:
        """占格格数，用于计算单格价值。"""
        if self.slot_w is None or self.slot_h is None:
            return None
        return self.slot_w * self.slot_h


@dataclass(frozen=True, slots=True)
class PriceRecord:
    """某个物品的一次最新价格快照。

    同时包含两种口径的涨跌幅：

    * `bl_today` / `day_3_bl` / `day_7_bl` / `day_30_bl`：数据源直接算好的；
    * 与"上一次采集""24 小时前"的比较由上层用本地历史快照计算。
    """

    external_id: str
    price: int | None
    price_start: int | None = None
    bl_today: float | None = None
    day_3_price: int | None = None
    day_3_bl: float | None = None
    day_7_price: int | None = None
    day_7_bl: float | None = None
    day_30_price: int | None = None
    day_30_bl: float | None = None
    #: 数据源给出的价格更新时间（数据帝字段 `is_get_time`），UTC naive
    source_updated_at: datetime | None = None
    #: 原始记录，原样存进 `current_price.raw_json`，便于日后扩展
    raw: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #
class DataSource(ABC):
    """数据源接口。

    只定义业务真正需要的两个动作：拉物品清单、拉最新价格。
    历史曲线接口（`minute`/`hour`/`day`）留到需要时再加，避免过早抽象。
    """

    #: 数据源标识，会写进 `current_price.source` 与 `collect_runs.source`
    name: str = "base"

    @abstractmethod
    def fetch_items(self) -> list[ItemRecord]:
        """拉取全量物品基础信息。"""

    @abstractmethod
    def fetch_prices(self) -> list[PriceRecord]:
        """拉取全量物品最新价格。"""

    def close(self) -> None:  # noqa: B027  有意留空：多数数据源无需释放资源
        """释放连接池等资源。默认无操作。"""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试
        return f"<{type(self).__name__} name={self.name!r}>"
