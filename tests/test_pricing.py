"""M4 验证：涨跌幅计算。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import Item, PriceHistory
from app.services.pricing import PriceChange, change_pct, load_price_changes

ANCHOR = datetime(2026, 10, 12, 16, 0, 0)


def add_item(session, item_id: str, name: str = "物品") -> Item:
    item = Item(item_id=item_id, name=name)
    session.add(item)
    return item


def add_snapshot(session, item_id: str, price: int, offset: timedelta) -> None:
    session.add(
        PriceHistory(item_id=item_id, price=price, recorded_at=ANCHOR - offset)
    )


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
