"""M4 验证：涨跌幅计算。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import Item, PriceHistory
from app.services.pricing import (
    PriceChange,
    beijing_day_start,
    change_pct,
    load_day_stats,
    load_price_changes,
)

ANCHOR = datetime(2026, 10, 12, 16, 0, 0)


def add_item(session, item_id: str, name: str = "物品") -> Item:
    item = Item(item_id=item_id, name=name)
    session.add(item)
    return item


def add_snapshot(session, item_id: str, price: int, offset: timedelta) -> None:
    session.add(
        PriceHistory(item_id=item_id, price=price, recorded_at=ANCHOR - offset)
    )


def add_at(session, item_id: str, price: int, recorded_at: datetime) -> None:
    """按绝对时间写一条快照（当天统计的用例要精确控制时间）。"""
    session.add(PriceHistory(item_id=item_id, price=price, recorded_at=recorded_at))


class TestChangePct:
    def test_rounds_to_two_decimals(self) -> None:
        assert change_pct(150, 100) == 50.0
        assert change_pct(100, 300) == -66.67

    def test_returns_none_when_reference_missing_or_zero(self) -> None:
        assert change_pct(100, None) is None
        assert change_pct(None, 100) is None
        assert change_pct(100, 0) is None


class TestLoadPriceChanges:
    def test_empty_history_returns_empty_mapping(self, session) -> None:
        assert load_price_changes(session) == {}

    def test_three_change_groups_are_computed(self, session) -> None:
        add_item(session, "1")
        for price, offset in (
            (100, timedelta(days=8)),
            (200, timedelta(days=7)),
            (400, timedelta(hours=30)),
            (500, timedelta(hours=6)),
            (600, timedelta(0)),
        ):
            add_snapshot(session, "1", price, offset)
        session.commit()

        change = load_price_changes(session)["1"]
        assert change.price == 600
        assert change.previous_price == 500
        assert change.previous_recorded_at is not None
        assert change.change_prev_pct == pytest.approx(20.0)
        assert change.change_24h_pct == pytest.approx(50.0)
        assert change.change_7d_pct == pytest.approx(200.0)

    def test_single_snapshot_yields_no_changes(self, session) -> None:
        add_item(session, "1")
        add_snapshot(session, "1", 777, timedelta(0))
        session.commit()

        change = load_price_changes(session)["1"]
        assert change.price == 777
        assert change.change_prev_pct is None
        assert change.change_24h_pct is None
        assert change.change_7d_pct is None

    def test_stale_item_does_not_report_zero_change(self, session) -> None:
        """3 天没数据的物品，不能因为参考点就是它自己而算出 0%。"""
        add_item(session, "fresh")
        add_snapshot(session, "fresh", 1000, timedelta(0))
        add_item(session, "stale")
        add_snapshot(session, "stale", 500, timedelta(days=3))
        session.commit()

        changes = load_price_changes(session)
        assert changes["stale"].change_24h_pct is None
        assert changes["stale"].change_7d_pct is None
        assert changes["stale"].change_prev_pct is None
        # 有历史的物品照常计算
        assert changes["fresh"].change_prev_pct is None

    def test_items_are_computed_independently(self, session) -> None:
        add_item(session, "a")
        add_snapshot(session, "a", 100, timedelta(hours=6))
        add_snapshot(session, "a", 200, timedelta(0))
        add_item(session, "b")
        add_snapshot(session, "b", 300, timedelta(hours=6))
        add_snapshot(session, "b", 150, timedelta(0))
        session.commit()

        changes = load_price_changes(session)
        assert changes["a"].change_prev_pct == pytest.approx(100.0)
        assert changes["b"].change_prev_pct == pytest.approx(-50.0)

    def test_price_change_dataclass_defaults(self) -> None:
        change = PriceChange()
        assert change.price is None
        assert change.change_24h_pct is None


#: 北京时间 2026-10-14 17:00（= UTC 09:00），用于固定"今天"是哪一天
NOW = datetime(2026, 10, 14, 9, 0, 0)
#: 北京时间当天 0 点补货那一刻（UTC 前一天 16:00）
RESTOCK_AT = datetime(2026, 10, 13, 16, 0, 0)


class TestBeijingDayStart:
    def test_shifts_by_eight_hours(self) -> None:
        assert beijing_day_start(NOW) == RESTOCK_AT

    def test_just_after_midnight_still_belongs_to_that_day(self) -> None:
        # UTC 16:00:30 = 北京时间次日 00:00:30，仍属于"今天"
        assert beijing_day_start(datetime(2026, 10, 13, 16, 0, 30)) == RESTOCK_AT

    def test_just_before_midnight_belongs_to_previous_day(self) -> None:
        # UTC 15:59 = 北京时间 23:59，属于前一天
        assert beijing_day_start(datetime(2026, 10, 13, 15, 59, 0)) == datetime(
            2026, 10, 12, 16, 0, 0
        )


class TestLoadDayStats:
    def test_restock_price_is_first_snapshot_of_the_day(self, session) -> None:
        add_item(session, "1")
        # 前一天的 23:00 快照（价格更高）不能当成补货价
        add_at(session, "1", 100, datetime(2026, 10, 13, 15, 0, 0))
        add_at(session, "1", 80, RESTOCK_AT)
        add_at(session, "1", 130, datetime(2026, 10, 14, 5, 0, 0))
        add_at(session, "1", 120, datetime(2026, 10, 14, 8, 0, 0))
        session.commit()

        stats = load_day_stats(session, NOW)["1"]
        assert stats.restock_price == 80
        assert stats.restock_at == RESTOCK_AT
        assert stats.day_high == 130
        assert stats.day_high_at == datetime(2026, 10, 14, 5, 0, 0)
        assert stats.spread == 50

    def test_tie_on_high_price_keeps_the_earlier_time(self, session) -> None:
        add_item(session, "1")
        add_at(session, "1", 80, RESTOCK_AT)
        add_at(session, "1", 120, datetime(2026, 10, 14, 3, 0, 0))
        add_at(session, "1", 120, datetime(2026, 10, 14, 8, 0, 0))
        session.commit()

        stats = load_day_stats(session, NOW)["1"]
        assert stats.day_high == 120
        assert stats.day_high_at == datetime(2026, 10, 14, 3, 0, 0)

    def test_item_without_today_snapshot_has_no_stats(self, session) -> None:
        add_item(session, "old")
        add_at(session, "old", 100, datetime(2026, 10, 12, 5, 0, 0))
        session.commit()

        assert "old" not in load_day_stats(session, NOW)

    def test_spread_is_zero_when_price_never_rose(self, session) -> None:
        """只跌不涨的当天，价差是 0（最高价就是补货价本身），不是负数。"""
        add_item(session, "1")
        add_at(session, "1", 100, RESTOCK_AT)
        add_at(session, "1", 70, datetime(2026, 10, 14, 8, 0, 0))
        session.commit()

        stats = load_day_stats(session, NOW)["1"]
        assert stats.day_high == 100
        assert stats.spread == 0

    def test_empty_history_returns_empty_mapping(self, session) -> None:
        assert load_day_stats(session, NOW) == {}
