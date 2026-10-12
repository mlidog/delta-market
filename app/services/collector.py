"""采集服务：把数据源的数据落进数据库。

职责边界：本模块只做"取数 → 落库 → 标记状态"，不处理 HTTP 细节（那是数据源的事），
也不做涨跌幅计算（那是 `pricing.py` 的事）。

失败处理原则：

* 可重试错误（网络、5xx、429）按指数退避重试，重试次数由配置决定；
* 不可重试错误（Token 无效、响应结构异常）立即失败；
* **取价失败时不写入任何新数据**，保留上一次价格，并把已有价格标记为
  `stale`（含错误原因与连续失败次数），同时写一条 `collect_runs` 审计记录；
* 取物品信息失败但取价成功时，仍写入价格（基础信息变化很慢，不该为此丢数据），
  整轮记为 `partial`。
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session, sessionmaker
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt

from app.config import Settings, get_settings
from app.data_sources import (
    DataSource,
    DataSourceError,
    DataSourceRateLimitError,
    ItemRecord,
    PriceRecord,
    create_data_source,
)
from app.database import SessionLocal
from app.models import CollectRun, CollectRunStatus, CurrentPrice, Item, PriceHistory, PriceStatus
from app.utils import utcnow

#: 指数退避的基础间隔（秒）：第 1 次重试前等 1s，第 2 次前等 4s，第 3 次前等 16s
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_FACTOR = 4.0
BACKOFF_MAX_SECONDS = 16.0

#: 价格批次里"本地目录找不到对应物品"的比例超过这个阈值，就认为目录已过期。
#: 典型场景：换了数据源，或者游戏更新加了一批新物品。
CATALOG_MISMATCH_MIN = 5
CATALOG_MISMATCH_RATIO = 0.10

#: 未匹配物品占价格批次的比例超过这个值，整轮才判定为"部分成功"。
#: 上游偶尔会有少量条目在基础信息库里缺失（实测 1383 条里有 23 条，约 1.7%），
#: 那是上游数据不一致，不是我们采集出了问题，不该让每一轮都显示异常。
UNMATCHED_TOLERANCE = 0.10


@dataclass(slots=True)
class CollectResult:
    """一轮采集的结果摘要，供日志与接口展示。"""

    run_id: int
    status: CollectRunStatus
    items_total: int = 0
    items_created: int = 0
    items_updated: int = 0
    #: 本轮是否真的去拉了物品基础信息（否则用的是本地缓存）
    items_refreshed: bool = False
    prices_total: int = 0
    prices_written: int = 0
    prices_skipped: int = 0
    history_written: int = 0
    stale_marked: int = 0
    #: 本轮的等待重试次数（不含首次调用）
    retries: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (CollectRunStatus.SUCCESS, CollectRunStatus.PARTIAL)


def _is_retryable(exc: BaseException) -> bool:
    """只有数据源明确标记为可重试的错误才重试。"""
    return isinstance(exc, DataSourceError) and exc.retryable


class Collector:
    """采集编排器。

    Args:
        session_factory: 会话工厂，测试时注入内存库。
        data_source_factory: 数据源工厂，测试时注入桩对象。
        settings: 配置，默认读全局配置。
        clock: 取当前时间的函数，测试可注入固定时间。
        sleep: 重试等待函数，测试可注入记录器以避免真的睡 16 秒。
        jitter_ratio: 退避抖动比例（默认 ±30%），测试可设为 0 得到确定值。
        rng: 抖动用的随机源。
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session] = SessionLocal,
        data_source_factory: Callable[[], DataSource] = create_data_source,
        settings: Settings | None = None,
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], None] = time.sleep,
        jitter_ratio: float = 0.3,
        rng: random.Random | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._data_source_factory = data_source_factory
        self._settings = settings or get_settings()
        self._clock = clock
        self._sleep = sleep
        self._jitter_ratio = jitter_ratio
        self._rng = rng or random.Random()
        self._retries = 0

    # ------------------------------------------------------------------ #
    # 对外入口
    # ------------------------------------------------------------------ #
    def run(self, source: DataSource | None = None) -> CollectResult:
        """执行一轮采集。"""
        started_at = self._clock()
        self._attempts = 0
        own_source = source is None
        data_source = source or self._data_source_factory()

        session = self._session_factory()
        try:
            run_row = CollectRun(
                source=data_source.name,
                started_at=started_at,
                status=CollectRunStatus.RUNNING.value,
            )
            session.add(run_row)
            session.commit()
            result = CollectResult(run_id=run_row.id, status=CollectRunStatus.RUNNING)

            try:
                self._collect(session, data_source, result, started_at)
            except DataSourceError as exc:
                session.rollback()
                self._mark_all_stale(session, str(exc))
                result.status = CollectRunStatus.FAILED
                result.error = str(exc)
            except Exception as exc:  # 非数据源异常：记录后继续抛出，避免掩盖程序缺陷
                session.rollback()
                self._finish_run(session, run_row, CollectRunStatus.FAILED, result, str(exc))
                raise

            result.retries = self._retries
            result.finished_at = self._clock()
            self._finish_run(session, run_row, result.status, result, result.error)
            return result
        finally:
            session.close()
            if own_source:
                data_source.close()

    # ------------------------------------------------------------------ #
    # 采集主流程
    # ------------------------------------------------------------------ #
    def _collect(
        self,
        session: Session,
        data_source: DataSource,
        result: CollectResult,
        started_at: datetime,
    ) -> None:
        items_error: str | None = None
        if self._should_refresh_items(session):
            items_error = self._refresh_items(session, data_source, result, started_at)
        else:
            result.items_total = int(
                session.scalar(select(func.count()).select_from(Item)) or 0
            )

        prices = self._with_retry(data_source.fetch_prices)
        result.prices_total = len(prices)

        # 目录与价格对不上（换了数据源，或游戏新增物品）时补一次目录再写价格。
        # 不补的话这一轮价格会全部落空——那 20 次资源的取价就白花了。
        if not result.items_refreshed and self._catalog_is_outdated(session, prices):
            items_error = (
                self._refresh_items(session, data_source, result, started_at) or items_error
            )

        known_ids = set(session.scalars(select(Item.item_id)).all())
        result.prices_written, result.prices_skipped, written_ids = self._write_prices(
            session, prices, known_ids, data_source.name
        )
        result.history_written = self._append_history(
            session, prices, started_at, data_source.name, written_ids
        )
        result.stale_marked = self._mark_missing_stale(session, prices)

        if result.prices_written == 0 and result.prices_skipped > 0:
            raise DataSourceError("全部物品都未能写入，本轮采集判定为失败")

        unmatch_ratio = (
            result.prices_skipped / result.prices_total if result.prices_total else 0.0
        )
        if items_error or unmatch_ratio > UNMATCHED_TOLERANCE:
            result.status = CollectRunStatus.PARTIAL
            result.error = items_error
        else:
            result.status = CollectRunStatus.SUCCESS

        session.commit()

    # ------------------------------------------------------------------ #
    # 重试
    # ------------------------------------------------------------------ #
    def _with_retry(self, func: Callable[[], Any]) -> Any:
        retrying = Retrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(max(1, self._settings.collector_retry_times)),
            wait=self._wait_strategy,
            sleep=self._sleep,
            reraise=True,
        )
        return retrying(func)

    def _wait_strategy(self, retry_state: RetryCallState) -> float:
        """指数退避 + 抖动；被限流时优先遵守服务端给出的 Retry-After。"""
        self._retries += 1
        attempt = retry_state.attempt_number
        delay = min(BACKOFF_BASE_SECONDS * BACKOFF_FACTOR ** (attempt - 1), BACKOFF_MAX_SECONDS)
        delay *= 1 + self._rng.uniform(-self._jitter_ratio, self._jitter_ratio)

        outcome = retry_state.outcome
        if outcome is not None:
            error = outcome.exception()
            if isinstance(error, DataSourceRateLimitError) and error.retry_after:
                delay = max(delay, error.retry_after)
        return max(0.0, delay)

    # ------------------------------------------------------------------ #
    # 落库
    # ------------------------------------------------------------------ #
    def _should_refresh_items(self, session: Session) -> bool:
        """是否需要去拉物品基础信息。

        `item_info_all` 与 `item_price_all` 各消耗 20 次资源，而基础信息
        （名称、分类、占格）几乎不变。默认只在本地为空或超过配置天数时刷新，
        否则每轮都白花 20 次资源。
        """
        days = self._settings.collector_item_refresh_days
        if days <= 0:
            return True
        newest = session.scalar(select(func.max(Item.updated_at)))
        if newest is None:
            return True
        age = self._clock() - newest
        # 时间戳落在未来（导入过演示数据、系统时间被调过）说明不可信，强制刷新一次
        return age < timedelta(0) or age >= timedelta(days=days)

    def _refresh_items(
        self,
        session: Session,
        data_source: DataSource,
        result: CollectResult,
        started_at: datetime,
    ) -> str | None:
        """拉取并落库物品基础信息；返回错误信息（成功返回 None）。"""
        try:
            items = self._with_retry(data_source.fetch_items)
        except DataSourceError as exc:
            # 基础信息取不到不致命：价格仍然可以写进已存在的物品
            return str(exc)

        result.items_total = len(items)
        result.items_refreshed = True
        result.items_created, result.items_updated = self._upsert_items(
            session, items, refreshed_at=started_at
        )
        # 立即提交：item_info_all 单次消耗 20 次资源，
        # 即使随后取价失败，也不该把已经花掉资源换来的数据丢掉。
        session.commit()
        return None

    def _catalog_is_outdated(self, session: Session, prices: list[PriceRecord]) -> bool:
        """价格里有多少条在本地目录中找不到对应物品。"""
        if not prices:
            return False
        local_ids = set(session.scalars(select(Item.item_id)).all())
        unknown = sum(1 for record in prices if record.external_id not in local_ids)
        return unknown >= CATALOG_MISMATCH_MIN and unknown >= len(prices) * CATALOG_MISMATCH_RATIO

    def _upsert_items(
        self,
        session: Session,
        items: list[ItemRecord],
        *,
        refreshed_at: datetime,
    ) -> tuple[int, int]:
        existing = {
            row.item_id: row for row in session.scalars(select(Item)).all()
        }
        created = updated = 0
        for record in items:
            row = existing.get(record.external_id)
            if row is None:
                session.add(
                    Item(
                        item_id=record.external_id,
                        name=record.name,
                        primary_class=record.primary_class,
                        second_class=record.second_class,
                        second_class_cn=record.second_class_cn,
                        grade=record.grade,
                        pic_url=record.pic_url,
                        is_tradable=record.is_tradable,
                        object_id=record.object_id,
                        slot_w=record.slot_w,
                        slot_h=record.slot_h,
                        created_at=refreshed_at,
                        updated_at=refreshed_at,
                    )
                )
                created += 1
            else:
                row.name = record.name
                row.primary_class = record.primary_class
                row.second_class = record.second_class
                row.second_class_cn = record.second_class_cn
                row.grade = record.grade
                row.pic_url = record.pic_url
                row.is_tradable = record.is_tradable
                row.object_id = record.object_id
                row.slot_w = record.slot_w
                row.slot_h = record.slot_h
                # 显式推进时间戳：它表示"目录最后核对时间"，而不是"这一行有没有变"。
                # 否则数据长期不变时，行时间会一直停在过去，导致每轮都判定为过期而重复付费。
                row.updated_at = refreshed_at
                updated += 1
        session.flush()
        return created, updated

    def _write_prices(
        self,
        session: Session,
        prices: list[PriceRecord],
        known_ids: set[str],
        source_name: str,
    ) -> tuple[int, int, set[str]]:
        existing = {
            row.item_id: row for row in session.scalars(select(CurrentPrice)).all()
        }
        now = self._clock()
        written = skipped = 0
        written_ids: set[str] = set()

        for record in prices:
            if record.external_id not in known_ids:
                # 价格没有对应的物品主数据，写进去会违反外键约束
                skipped += 1
                continue

            row = existing.get(record.external_id)
            if row is None:
                row = CurrentPrice(item_id=record.external_id)
                session.add(row)
            row.price = record.price
            row.price_start = record.price_start
            row.bl_today = record.bl_today
            row.day_3_price = record.day_3_price
            row.day_3_bl = record.day_3_bl
            row.day_7_price = record.day_7_price
            row.day_7_bl = record.day_7_bl
            row.day_30_price = record.day_30_price
            row.day_30_bl = record.day_30_bl
            row.source_updated_at = record.source_updated_at
            row.raw_json = _dump_raw(record.raw)
            row.source = source_name
            row.updated_at = now
            # 采集成功：清除失败痕迹
            row.status = PriceStatus.OK.value
            row.last_error = None
            row.consecutive_failures = 0
            written += 1
            written_ids.add(record.external_id)

        session.flush()
        return written, skipped, written_ids

    def _append_history(
        self,
        session: Session,
        prices: list[PriceRecord],
        recorded_at: datetime,
        source_name: str,
        written_ids: set[str],
    ) -> int:
        """追加价格快照。同一时刻的重复采集幂等（靠联合唯一约束与预查去重）。"""
        rows = [
            {
                "item_id": record.external_id,
                "price": record.price,
                "source": source_name,
                "recorded_at": recorded_at,
            }
            for record in prices
            if record.price is not None and record.external_id in written_ids
        ]
        if not rows:
            return 0

        already = set(
            session.scalars(
                select(PriceHistory.item_id).where(PriceHistory.recorded_at == recorded_at)
            ).all()
        )
        fresh = [row for row in rows if row["item_id"] not in already]
        if fresh:
            session.execute(insert(PriceHistory), fresh)
        return len(fresh)

    def _mark_missing_stale(self, session: Session, prices: list[PriceRecord]) -> int:
        """本次采集没返回的历史物品，标记为 stale（可能是下架或接口异常）。"""
        if not prices:
            return 0
        seen = {record.external_id for record in prices}
        result = session.execute(
            update(CurrentPrice)
            .where(
                CurrentPrice.item_id.not_in(seen),
                CurrentPrice.status == PriceStatus.OK.value,
            )
            .values(
                status=PriceStatus.STALE.value,
                last_error="本次采集未返回该物品",
                consecutive_failures=CurrentPrice.consecutive_failures + 1,
            )
        )
        return result.rowcount or 0

    def _mark_all_stale(self, session: Session, reason: str) -> int:
        """整轮采集失败：保留价格，只标记状态。"""
        result = session.execute(
            update(CurrentPrice).values(
                status=PriceStatus.STALE.value,
                last_error=reason,
                consecutive_failures=CurrentPrice.consecutive_failures + 1,
            )
        )
        session.commit()
        return result.rowcount or 0

    def _finish_run(
        self,
        session: Session,
        run_row: CollectRun,
        status: CollectRunStatus,
        result: CollectResult,
        error: str | None,
    ) -> None:
        run_row.status = status.value
        run_row.finished_at = result.finished_at or self._clock()
        run_row.items_ok = result.prices_written
        run_row.items_failed = result.prices_skipped
        run_row.error = error
        session.commit()

def _dump_raw(raw: dict[str, Any] | None) -> str | None:
    if raw is None:
        return None
    return json.dumps(raw, ensure_ascii=False, sort_keys=True)
