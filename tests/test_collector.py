"""M3 验证：采集落库、失败隔离与重试策略。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.data_sources import (
    DataSource,
    DataSourceAuthError,
    DataSourceRateLimitError,
    DataSourceUnavailableError,
    ItemRecord,
    ManufactureRecord,
    MockDataSource,
    PriceRecord,
)
from app.models import CollectRun, CollectRunStatus, CurrentPrice, Item, PriceHistory, PriceStatus
from app.services import Collector, CollectResult

BASE_TIME = datetime(2026, 10, 12, 16, 0, tzinfo=UTC).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# 测试用桩数据源
# --------------------------------------------------------------------------- #
class StubSource(DataSource):
    """按预设顺序抛错的桩数据源，用来精确驱动重试与失败分支。"""

    name = "stub"

    def __init__(
        self,
        items: list[ItemRecord],
        prices: list[PriceRecord],
        item_errors: tuple[BaseException, ...] = (),
        price_errors: tuple[BaseException, ...] = (),
        manufacture: list[ManufactureRecord] | None = None,
    ) -> None:
        self._items = list(items)
        self._prices = list(prices)
        self._item_errors = list(item_errors)
        self._price_errors = list(price_errors)
        self._manufacture = list(manufacture or [])
        self.item_calls = 0
        self.price_calls = 0

    def fetch_items(self) -> list[ItemRecord]:
        self.item_calls += 1
        if self._item_errors:
            raise self._item_errors.pop(0)
        return list(self._items)

    def fetch_prices(self) -> list[PriceRecord]:
        self.price_calls += 1
        if self._price_errors:
            raise self._price_errors.pop(0)
        return list(self._prices)

    def fetch_manufacture(self, station_id: int, level: int) -> list[ManufactureRecord]:
        return list(self._manufacture)


def make_item(item_id: str, name: str = "测试物品", **kwargs) -> ItemRecord:
    return ItemRecord(external_id=item_id, name=name, primary_class="collection", **kwargs)


def make_price(item_id: str, price: int, **kwargs) -> PriceRecord:
    return PriceRecord(external_id=item_id, price=price, **kwargs)


def make_collector(
    session_factory,
    *,
    retry_times: int = 3,
    clock=BASE_TIME,
    sleep=None,
    jitter_ratio: float = 0.0,
    item_refresh_days: int = 7,
) -> Collector:
    # 默认不真的睡：只有校验退避时间的用例才传入记录器
    sleeper = sleep if sleep is not None else (lambda _seconds: None)
    return Collector(
        session_factory=session_factory,
        settings=Settings(
            _env_file=None,
            collector_retry_times=retry_times,
            collector_item_refresh_days=item_refresh_days,
        ),
        clock=lambda: clock,
        jitter_ratio=jitter_ratio,
        sleep=sleeper,
    )


@pytest.fixture()
def two_items() -> list[ItemRecord]:
    return [make_item("1001", "物品甲"), make_item("1002", "物品乙")]


@pytest.fixture()
def two_prices() -> list[PriceRecord]:
    return [make_price("1001", 1000), make_price("1002", 2000)]


# --------------------------------------------------------------------------- #
# 正常路径
# --------------------------------------------------------------------------- #
class TestSuccessfulRun:
    def test_writes_items_prices_and_history(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        source = StubSource(two_items, two_prices)
        result = make_collector(session_factory).run(source)

        assert result.status is CollectRunStatus.SUCCESS
        assert result.items_created == 2
        assert result.prices_written == 2
        assert result.history_written == 2
        assert result.prices_skipped == 0
        assert session.scalar(select(func.count()).select_from(Item)) == 2
        assert session.scalar(select(func.count()).select_from(CurrentPrice)) == 2
        assert session.scalar(select(func.count()).select_from(PriceHistory)) == 2

    def test_records_source_name_on_price_rows(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory).run(StubSource(two_items, two_prices))
        sources = set(session.scalars(select(CurrentPrice.source)).all())
        history_sources = set(session.scalars(select(PriceHistory.source)).all())
        assert sources == {"stub"}
        assert history_sources == {"stub"}

    def test_writes_run_audit_row(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        result = make_collector(session_factory).run(StubSource(two_items, two_prices))
        run = session.get(CollectRun, result.run_id)
        assert run is not None
        assert run.status == CollectRunStatus.SUCCESS.value
        assert run.source == "stub"
        assert run.items_ok == 2
        assert run.items_failed == 0
        assert run.finished_at is not None
        assert run.error is None

    def test_persists_platform_fields_and_raw_json(
        self, session_factory, session
    ) -> None:
        record = PriceRecord(
            external_id="1001",
            price=25673,
            price_start=25000,
            bl_today=-31.57,
            day_7_price=30000,
            day_7_bl=-14.42,
            raw={"id": 1001, "price": 25673, "is_get_time": 1761911266},
        )
        make_collector(session_factory).run(
            StubSource([make_item("1001")], [record])
        )
        row = session.get(CurrentPrice, "1001")
        assert row is not None
        assert row.price == 25673
        assert row.price_start == 25000
        assert row.bl_today == pytest.approx(-31.57)
        assert row.day_7_bl == pytest.approx(-14.42)
        assert row.raw_json is not None and '"is_get_time": 1761911266' in row.raw_json
        assert row.status == PriceStatus.OK.value

    def test_second_run_at_other_time_appends_history(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory, clock=BASE_TIME).run(
            StubSource(two_items, two_prices)
        )
        later = BASE_TIME + timedelta(hours=6)
        second = make_collector(session_factory, clock=later).run(
            StubSource(two_items, two_prices)
        )

        assert second.items_created == 0
        # 目录还在缓存期内，不会再花 20 次资源去拉一遍基础信息
        assert second.items_updated == 0
        assert second.items_refreshed is False
        assert second.history_written == 2
        assert session.scalar(select(func.count()).select_from(PriceHistory)) == 4
        assert session.scalar(select(func.count()).select_from(CurrentPrice)) == 2

    def test_duplicate_run_at_same_moment_is_idempotent(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory).run(StubSource(two_items, two_prices))
        second = make_collector(session_factory).run(StubSource(two_items, two_prices))

        assert second.history_written == 0
        assert session.scalar(select(func.count()).select_from(PriceHistory)) == 2

    def test_end_to_end_with_mock_source(self, session_factory, session) -> None:
        source = MockDataSource(clock=lambda: BASE_TIME)
        result = make_collector(session_factory).run(source)

        assert result.status is CollectRunStatus.SUCCESS
        assert result.items_total == result.items_created == 25
        # 25 个物品里有 2 个不可交易，价格接口不返回它们
        assert result.prices_written == 23
        assert session.scalar(
            select(func.count()).select_from(PriceHistory)
        ) == 23


# --------------------------------------------------------------------------- #
# 失败处理
# --------------------------------------------------------------------------- #
class TestFailureHandling:
    def test_price_failure_keeps_previous_prices(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory).run(StubSource(two_items, two_prices))
        failing = StubSource(
            two_items, two_prices, price_errors=(DataSourceAuthError("token 无效"),)
        )
        result = make_collector(session_factory, clock=BASE_TIME + timedelta(hours=6)).run(
            failing
        )

        assert result.status is CollectRunStatus.FAILED
        assert result.error is not None and "token" in result.error
        assert session.scalar(select(func.count()).select_from(PriceHistory)) == 2
        assert session.get(CurrentPrice, "1001").price == 1000

    def test_price_failure_marks_prices_stale(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory).run(StubSource(two_items, two_prices))
        failing = StubSource(
            two_items, two_prices, price_errors=(DataSourceAuthError("token 无效"),)
        )
        make_collector(session_factory, clock=BASE_TIME + timedelta(hours=6)).run(failing)

        rows = session.scalars(select(CurrentPrice)).all()
        assert {row.status for row in rows} == {PriceStatus.STALE.value}
        assert all(row.is_stale for row in rows)
        assert all(row.consecutive_failures == 1 for row in rows)
        assert all(row.last_error == "token 无效" for row in rows)

    def test_repeated_failures_accumulate_counter(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory).run(StubSource(two_items, two_prices))
        for offset in (6, 12):
            failing = StubSource(
                two_items, two_prices, price_errors=(DataSourceAuthError("挂了"),)
            )
            make_collector(session_factory, clock=BASE_TIME + timedelta(hours=offset)).run(
                failing
            )

        assert all(
            row.consecutive_failures == 2
            for row in session.scalars(select(CurrentPrice)).all()
        )

    def test_recovery_clears_stale_state(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory).run(StubSource(two_items, two_prices))
        make_collector(session_factory, clock=BASE_TIME + timedelta(hours=6)).run(
            StubSource(two_items, two_prices, price_errors=(DataSourceAuthError("挂了"),))
        )
        healthy = [
            make_price("1001", 1500),
            make_price("1002", 2500),
        ]
        result = make_collector(
            session_factory, clock=BASE_TIME + timedelta(hours=12)
        ).run(StubSource(two_items, healthy))

        assert result.status is CollectRunStatus.SUCCESS
        rows = session.scalars(select(CurrentPrice)).all()
        assert {row.status for row in rows} == {PriceStatus.OK.value}
        assert all(row.consecutive_failures == 0 for row in rows)
        assert all(row.last_error is None for row in rows)

    def test_items_failure_still_writes_prices(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory).run(StubSource(two_items, two_prices))
        later_prices = [make_price("1001", 1300), make_price("1002", 2300)]
        source = StubSource(
            two_items, later_prices, item_errors=(DataSourceAuthError("基础信息挂了"),)
        )
        # 强制刷新基础信息（item_refresh_days=0），否则会因为目录还在缓存期内而根本不发起请求
        result = make_collector(
            session_factory,
            clock=BASE_TIME + timedelta(hours=6),
            item_refresh_days=0,
        ).run(source)

        assert result.status is CollectRunStatus.PARTIAL
        assert result.error is not None and "基础信息" in result.error
        assert result.prices_written == 2
        assert session.get(CurrentPrice, "1001").price == 1300

    def test_items_are_kept_even_when_price_fetch_fails(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        """item_info_all 单次消耗 20 次资源，取价失败也不该丢掉它。"""
        source = StubSource(
            two_items, two_prices, price_errors=(DataSourceAuthError("取价失败"),)
        )
        result = make_collector(session_factory).run(source)

        assert result.status is CollectRunStatus.FAILED
        assert session.scalar(select(func.count()).select_from(Item)) == 2

    def test_first_run_without_items_cannot_write_prices(self, session_factory) -> None:
        source = StubSource(
            [], [make_price("1001", 1000)], item_errors=(DataSourceAuthError("无物品"),)
        )
        result = make_collector(session_factory).run(source)

        assert result.status is CollectRunStatus.FAILED
        assert result.prices_written == 0
        assert result.prices_skipped == 1

    def test_unknown_item_price_is_skipped(self, session_factory, session) -> None:
        prices = [make_price("1001", 1000), make_price("9999", 5000)]
        result = make_collector(session_factory).run(
            StubSource([make_item("1001")], prices)
        )

        assert result.prices_written == 1
        assert result.prices_skipped == 1
        assert result.status is CollectRunStatus.PARTIAL
        assert session.scalar(select(func.count()).select_from(PriceHistory)) == 1

    def test_delisted_item_is_marked_stale(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory).run(StubSource(two_items, two_prices))
        source = StubSource(two_items, [make_price("1001", 1200)])
        result = make_collector(session_factory, clock=BASE_TIME + timedelta(hours=6)).run(
            source
        )

        assert result.stale_marked == 1
        assert session.get(CurrentPrice, "1002").is_stale is True
        assert session.get(CurrentPrice, "1002").last_error == "本次采集未返回该物品"
        assert session.get(CurrentPrice, "1001").is_stale is False

    def test_failed_run_is_recorded_in_audit_table(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        source = StubSource(
            two_items, two_prices, price_errors=(DataSourceAuthError("token 无效"),)
        )
        result = make_collector(session_factory).run(source)

        run = session.get(CollectRun, result.run_id)
        assert run is not None
        assert run.status == CollectRunStatus.FAILED.value
        assert run.error == "token 无效"
        assert run.finished_at is not None


# --------------------------------------------------------------------------- #
# 重试策略
# --------------------------------------------------------------------------- #
class TestRetryPolicy:
    def test_retryable_error_is_retried_until_success(
        self, session_factory, two_items, two_prices
    ) -> None:
        source = StubSource(
            two_items,
            two_prices,
            price_errors=(
                DataSourceUnavailableError("超时"),
                DataSourceUnavailableError("超时"),
            ),
        )
        result = make_collector(session_factory, retry_times=3).run(source)

        assert result.status is CollectRunStatus.SUCCESS
        assert source.price_calls == 3

    def test_retry_gives_up_after_configured_attempts(
        self, session_factory, two_items, two_prices
    ) -> None:
        source = StubSource(
            two_items,
            two_prices,
            price_errors=(
                DataSourceUnavailableError("超时"),
                DataSourceUnavailableError("超时"),
                DataSourceUnavailableError("超时"),
                DataSourceUnavailableError("超时"),
            ),
        )
        result = make_collector(session_factory, retry_times=3).run(source)

        assert result.status is CollectRunStatus.FAILED
        assert source.price_calls == 3

    def test_non_retryable_error_is_not_retried(
        self, session_factory, two_items, two_prices
    ) -> None:
        source = StubSource(
            two_items, two_prices, price_errors=(DataSourceAuthError("token 无效"),)
        )
        result = make_collector(session_factory, retry_times=5).run(source)

        assert result.status is CollectRunStatus.FAILED
        assert source.price_calls == 1

    def test_backoff_is_exponential(
        self, session_factory, two_items, two_prices
    ) -> None:
        delays: list[float] = []
        source = StubSource(
            two_items,
            two_prices,
            price_errors=(
                DataSourceUnavailableError("1"),
                DataSourceUnavailableError("2"),
            ),
        )
        make_collector(session_factory, retry_times=3, sleep=delays.append).run(source)

        assert delays == [1.0, 4.0]

    def test_rate_limit_honours_retry_after(
        self, session_factory, two_items, two_prices
    ) -> None:
        delays: list[float] = []
        source = StubSource(
            two_items,
            two_prices,
            price_errors=(DataSourceRateLimitError("限流", retry_after=7.0),),
        )
        make_collector(session_factory, retry_times=2, sleep=delays.append).run(source)

        assert delays == [7.0]

    def test_retry_count_is_reported(
        self, session_factory, two_items, two_prices
    ) -> None:
        source = StubSource(
            two_items, two_prices, price_errors=(DataSourceUnavailableError("超时"),)
        )
        result = make_collector(session_factory, retry_times=3).run(source)
        assert result.retries == 1


class TestItemRefreshPolicy:
    """物品基础信息按天缓存：item_info_all 每轮价值 20 次资源，不能白花。"""

    def test_first_run_fetches_items(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        source = StubSource(two_items, two_prices)
        result = make_collector(session_factory).run(source)
        assert source.item_calls == 1
        assert result.items_refreshed is True
        assert result.items_created == 2

    def test_fresh_catalog_is_not_refetched(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory, clock=BASE_TIME).run(
            StubSource(two_items, two_prices)
        )
        second_source = StubSource(
            two_items, [make_price("1001", 1100), make_price("1002", 2200)]
        )
        result = make_collector(
            session_factory, clock=BASE_TIME + timedelta(hours=6)
        ).run(second_source)

        assert second_source.item_calls == 0
        assert result.items_refreshed is False
        assert result.items_total == 2  # 用本地目录里的数量
        assert result.prices_written == 2  # 价格照常刷新
        assert result.status is CollectRunStatus.SUCCESS

    def test_catalog_is_refetched_after_the_interval(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory, clock=BASE_TIME).run(
            StubSource(two_items, two_prices)
        )
        second_source = StubSource(two_items, two_prices)
        result = make_collector(
            session_factory, clock=BASE_TIME + timedelta(days=8), item_refresh_days=7
        ).run(second_source)

        assert second_source.item_calls == 1
        assert result.items_refreshed is True
        assert result.items_updated == 2

    def test_interval_zero_forces_refresh_every_run(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory, clock=BASE_TIME).run(
            StubSource(two_items, two_prices)
        )
        second_source = StubSource(two_items, two_prices)
        make_collector(
            session_factory, clock=BASE_TIME + timedelta(hours=1), item_refresh_days=0
        ).run(second_source)
        assert second_source.item_calls == 1

    def test_catalog_timestamp_advances_only_on_refresh(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        make_collector(session_factory, clock=BASE_TIME).run(
            StubSource(two_items, two_prices)
        )
        make_collector(session_factory, clock=BASE_TIME + timedelta(hours=6)).run(
            StubSource(two_items, two_prices)
        )
        stamps = set(session.scalars(select(Item.updated_at)).all())
        assert stamps == {BASE_TIME}

    def test_failed_refresh_is_retried_next_run(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        """取基础信息失败后，下一轮必须重试，不能把空目录当成"新鲜"。"""
        failing = StubSource(
            two_items, two_prices, item_errors=(DataSourceAuthError("基础信息挂了"),)
        )
        make_collector(session_factory, clock=BASE_TIME).run(failing)

        retry_source = StubSource(two_items, two_prices)
        result = make_collector(
            session_factory, clock=BASE_TIME + timedelta(hours=6)
        ).run(retry_source)
        assert retry_source.item_calls == 1
        assert result.items_refreshed is True
        assert result.items_created == 2


class TestCatalogSelfHealing:
    """目录与价格对不上时的自愈：不能让这一轮的取价白白花掉。"""

    def test_outdated_catalog_is_refreshed_before_writing_prices(
        self, session_factory, session
    ) -> None:
        make_collector(session_factory).run(
            StubSource([make_item("1")], [make_price("1", 100)])
        )

        # 第二轮：本地目录看着还新鲜，但价格里全是没见过的新物品
        new_items = [make_item(str(i)) for i in range(2, 8)]
        prices = [make_price(str(i), 100 * i) for i in range(2, 8)]
        source = StubSource(new_items, prices)
        result = make_collector(session_factory, clock=BASE_TIME + timedelta(hours=1)).run(
            source
        )

        assert source.item_calls == 1  # 额外补了一次目录
        assert result.items_refreshed is True
        assert result.prices_written == 6
        assert result.prices_skipped == 0
        assert result.status is CollectRunStatus.SUCCESS

    def test_single_new_item_does_not_trigger_an_extra_refresh(
        self, session_factory, session
    ) -> None:
        """偶尔冒出一两个新物品不值得花 20 次资源重拉目录。"""
        existing = [make_item(str(i)) for i in range(1, 21)]
        make_collector(session_factory).run(
            StubSource(existing, [make_price(str(i), 100) for i in range(1, 21)])
        )

        prices = [make_price(str(i), 100) for i in range(1, 22)]  # 21 号是新物品
        source = StubSource([make_item("21")], prices)
        result = make_collector(session_factory, clock=BASE_TIME + timedelta(hours=1)).run(
            source
        )

        assert source.item_calls == 0
        assert result.prices_written == 20
        assert result.prices_skipped == 1
        # 偶尔 1 条对不上属于上游噪声，不升级成异常状态
        assert result.status is CollectRunStatus.SUCCESS

    def test_future_catalog_timestamp_forces_refresh(
        self, session_factory, session, two_items, two_prices
    ) -> None:
        """时间戳落在未来（导入过演示数据、改过系统时间）时目录不可信。"""
        make_collector(session_factory, clock=BASE_TIME + timedelta(days=3)).run(
            StubSource(two_items, two_prices)
        )
        source = StubSource(two_items, two_prices)
        result = make_collector(session_factory, clock=BASE_TIME).run(source)

        assert source.item_calls == 1
        assert result.items_refreshed is True


class TestCollectResult:
    def test_ok_flag_reflects_status(self) -> None:
        assert CollectResult(run_id=1, status=CollectRunStatus.SUCCESS).ok is True
        assert CollectResult(run_id=1, status=CollectRunStatus.PARTIAL).ok is True
        assert CollectResult(run_id=1, status=CollectRunStatus.FAILED).ok is False
