"""M4 验证：四个接口的返回结构与行为。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import CollectRun, CollectRunStatus, CurrentPrice, Item, PriceHistory, PriceStatus

ANCHOR = datetime(2026, 10, 12, 16, 0, 0)


@pytest.fixture()
def seeded(session):
    """一批确定性的数据：2 个可交易物品（一个有完整历史、一个是 stale）+ 1 个不可交易物品。"""
    session.add_all(
        [
            Item(
                item_id="900001",
                name="测试枪械",
                primary_class="gun",
                second_class_cn="突击步枪",
                grade=4,
                slot_w=2,
                slot_h=4,
            ),
            Item(
                item_id="900002",
                name="测试子弹",
                primary_class="ammo",
                second_class_cn="ammo5.56x45",
                grade=5,
                slot_w=1,
                slot_h=1,
            ),
            Item(
                item_id="900003",
                name="不可交易品",
                primary_class="collection",
                second_class_cn="收集品",
                grade=6,
                is_tradable=False,
                slot_w=1,
                slot_h=1,
            ),
        ]
    )
    session.add_all(
        [
            CurrentPrice(
                item_id="900001",
                price=600,
                price_start=400,
                bl_today=50.0,
                day_3_bl=20.0,
                day_7_bl=200.0,
                day_30_bl=300.0,
                source="mock",
                status=PriceStatus.OK.value,
                source_updated_at=ANCHOR,
                updated_at=ANCHOR,
            ),
            CurrentPrice(
                item_id="900002",
                price=100,
                price_start=100,
                bl_today=0.0,
                source="mock",
                status=PriceStatus.STALE.value,
                last_error="模拟取数失败",
                consecutive_failures=1,
                updated_at=ANCHOR,
            ),
        ]
    )
    for price, offset in (
        (100, timedelta(days=8)),
        (200, timedelta(days=7)),
        (400, timedelta(hours=30)),
        (500, timedelta(hours=6)),
        (600, timedelta(0)),
    ):
        session.add(
            PriceHistory(item_id="900001", price=price, recorded_at=ANCHOR - offset)
        )
    session.add(
        PriceHistory(item_id="900002", price=50, recorded_at=ANCHOR - timedelta(days=2))
    )
    session.add(PriceHistory(item_id="900002", price=100, recorded_at=ANCHOR))
    session.commit()
    return session


def get_items(client, **params):
    response = client.get("/api/items", params=params)
    assert response.status_code == 200, response.text
    return response.json()


class TestHealth:
    def test_reports_core_state(self, client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert body["data_source"] == "mock"
        assert body["scheduler_running"] is False
        assert body["version"]

    def test_timestamps_are_utc_marked(self, client) -> None:
        body = client.get("/health").json()
        assert body["server_time"].endswith("Z")


class TestItemList:
    def test_returns_all_items_with_envelope(self, client, seeded) -> None:
        body = get_items(client)
        assert body["total"] == 3
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert len(body["items"]) == 3

    def test_default_sort_is_price_desc_with_nulls_last(self, client, seeded) -> None:
        body = get_items(client)
        assert [item["price"] for item in body["items"]] == [600, 100, None]

    def test_price_ascending_sort(self, client, seeded) -> None:
        body = get_items(client, sort="price", order="asc")
        assert [item["price"] for item in body["items"]] == [100, 600, None]

    def test_filter_by_category(self, client, seeded) -> None:
        body = get_items(client, category="gun")
        assert body["total"] == 1
        assert body["items"][0]["item_id"] == "900001"

    def test_filter_by_sub_category(self, client, seeded) -> None:
        body = get_items(client, sub_category="ammo5.56x45")
        assert body["total"] == 1
        assert body["items"][0]["name"] == "测试子弹"

    def test_filter_by_grade(self, client, seeded) -> None:
        body = get_items(client, grade=6)
        assert body["total"] == 1
        assert body["items"][0]["item_id"] == "900003"

    def test_filter_by_tradable(self, client, seeded) -> None:
        assert get_items(client, tradable=False)["total"] == 1
        assert get_items(client, tradable=True)["total"] == 2

    def test_pagination(self, client, seeded) -> None:
        first = get_items(client, limit=1, offset=0)
        second = get_items(client, limit=1, offset=1)
        assert first["total"] == second["total"] == 3
        assert len(first["items"]) == len(second["items"]) == 1
        assert first["items"][0]["item_id"] != second["items"][0]["item_id"]

    def test_limit_above_cap_is_rejected(self, client, seeded) -> None:
        assert client.get("/api/items", params={"limit": 500}).status_code == 422

    def test_unknown_sort_field_is_rejected(self, client, seeded) -> None:
        assert client.get("/api/items", params={"sort": "nope"}).status_code == 422

    def test_platform_change_fields_are_exposed(self, client, seeded) -> None:
        item = get_items(client, category="gun")["items"][0]
        assert item["bl_today"] == pytest.approx(50.0)
        assert item["day_7_bl"] == pytest.approx(200.0)
        assert item["day_30_bl"] == pytest.approx(300.0)

    def test_local_change_fields_use_history(self, client, seeded) -> None:
        item = get_items(client, category="gun")["items"][0]
        assert item["change_prev_pct"] == pytest.approx(20.0)
        assert item["change_24h_pct"] == pytest.approx(50.0)
        assert item["change_7d_pct"] == pytest.approx(200.0)

    def test_change_field_is_null_when_history_is_short(self, client, seeded) -> None:
        item = get_items(client, category="ammo")["items"][0]
        assert item["change_prev_pct"] == pytest.approx(100.0)
        assert item["change_24h_pct"] == pytest.approx(100.0)
        assert item["change_7d_pct"] is None

    def test_sort_by_local_change_pct(self, client, seeded) -> None:
        body = get_items(client, sort="change_24h_pct", order="desc")
        assert [item["item_id"] for item in body["items"]][:2] == ["900002", "900001"]
        assert body["items"][-1]["change_24h_pct"] is None

    def test_single_slot_value_is_derived(self, client, seeded) -> None:
        gun = get_items(client, category="gun")["items"][0]
        assert gun["slot_area"] == 8
        assert gun["price_per_slot"] == 75  # 600 // 8
        ammo = get_items(client, category="ammo")["items"][0]
        assert ammo["price_per_slot"] == 100

    def test_stale_status_is_surfaced(self, client, seeded) -> None:
        ammo = get_items(client, category="ammo")["items"][0]
        assert ammo["status"] == "stale"
        assert ammo["is_stale"] is True
        gun = get_items(client, category="gun")["items"][0]
        assert gun["is_stale"] is False

    def test_item_without_price_has_unknown_status(self, client, seeded) -> None:
        item = get_items(client, tradable=False)["items"][0]
        assert item["price"] is None
        assert item["status"] == "unknown"
        assert item["change_24h_pct"] is None

    def test_timestamps_are_utc_marked(self, client, seeded) -> None:
        item = get_items(client, category="gun")["items"][0]
        assert item["updated_at"].endswith("Z")
        assert item["source_updated_at"].endswith("Z")

    def test_empty_database_returns_empty_page(self, client) -> None:
        body = get_items(client)
        assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}

    def test_prices_from_other_sources_are_hidden(self, client, session, seeded) -> None:
        """换数据源后，另一套数据不该混进榜单。"""
        session.add(Item(item_id="777001", name="别的数据源物品", primary_class="gun", grade=3))
        session.add(
            CurrentPrice(
                item_id="777001",
                price=999,
                source="delta",
                status=PriceStatus.OK.value,
                updated_at=ANCHOR,
            )
        )
        session.commit()

        body = get_items(client)
        assert [item["item_id"] for item in body["items"]] != ["777001"]
        assert all(item["item_id"] != "777001" for item in body["items"])
        assert body["total"] == 3  # 原有的三个物品照常


class TestItemHistory:
    def test_default_period_is_24h(self, client, seeded) -> None:
        body = client.get("/api/items/900001/history").json()
        assert body["period"] == "24h"
        assert body["point_count"] == 2
        assert [point["price"] for point in body["points"]] == [500, 600]
        assert body["change_pct"] == pytest.approx(20.0)

    def test_points_are_ordered_ascending(self, client, seeded) -> None:
        points = client.get("/api/items/900001/history", params={"period": "30d"}).json()[
            "points"
        ]
        times = [point["t"] for point in points]
        assert times == sorted(times)

    def test_one_hour_period_has_single_point(self, client, seeded) -> None:
        body = client.get("/api/items/900001/history", params={"period": "1h"}).json()
        assert body["point_count"] == 1
        assert body["change_pct"] is None

    def test_seven_day_window(self, client, seeded) -> None:
        body = client.get("/api/items/900001/history", params={"period": "7d"}).json()
        assert body["point_count"] == 4
        assert body["change_pct"] == pytest.approx(200.0)

    def test_thirty_day_window_uses_oldest_point(self, client, seeded) -> None:
        body = client.get("/api/items/900001/history", params={"period": "30d"}).json()
        assert body["point_count"] == 5
        assert body["change_pct"] == pytest.approx(500.0)

    def test_includes_item_name(self, client, seeded) -> None:
        assert client.get("/api/items/900001/history").json()["name"] == "测试枪械"

    def test_unknown_item_returns_404(self, client, seeded) -> None:
        response = client.get("/api/items/nope/history")
        assert response.status_code == 404
        assert "不存在" in response.json()["detail"]

    def test_invalid_period_is_rejected(self, client, seeded) -> None:
        assert client.get("/api/items/900001/history", params={"period": "1y"}).status_code == 422

    def test_item_without_history_returns_empty_points(self, client, seeded) -> None:
        body = client.get("/api/items/900003/history").json()
        assert body["points"] == []
        assert body["point_count"] == 0
        assert body["change_pct"] is None

    def test_point_timestamps_are_utc_marked(self, client, seeded) -> None:
        body = client.get("/api/items/900001/history").json()
        assert body["points"][0]["t"].endswith("Z")


class TestDashboardSummary:
    def test_counts_items_and_directions(self, client, seeded) -> None:
        body = client.get("/api/dashboard/summary").json()
        assert body["item_count"] == 3
        assert body["tradable_count"] == 2
        assert body["priced_count"] == 2
        assert body["rising_count"] == 1
        assert body["falling_count"] == 0
        assert body["flat_count"] == 1
        assert body["stale_count"] == 1

    def test_reports_data_source(self, client, seeded) -> None:
        assert client.get("/api/dashboard/summary").json()["data_source"] == "mock"

    def test_last_collect_is_null_without_runs(self, client, seeded) -> None:
        assert client.get("/api/dashboard/summary").json()["last_collect"] is None

    def test_last_collect_reflects_latest_run(self, client, session, seeded) -> None:
        session.add(
            CollectRun(
                source="mock",
                status=CollectRunStatus.SUCCESS.value,
                items_ok=23,
                items_failed=0,
                started_at=ANCHOR,
                finished_at=ANCHOR,
            )
        )
        session.commit()

        body = client.get("/api/dashboard/summary").json()
        assert body["last_collect"]["status"] == "success"
        assert body["last_collect"]["items_ok"] == 23
        assert body["last_collect"]["started_at"].endswith("Z")

    def test_generated_at_is_utc_marked(self, client, seeded) -> None:
        assert client.get("/api/dashboard/summary").json()["generated_at"].endswith("Z")

    def test_empty_database_is_all_zero(self, client) -> None:
        body = client.get("/api/dashboard/summary").json()
        assert body["item_count"] == 0
        assert body["rising_count"] == 0
        assert body["stale_count"] == 0

    def test_counts_ignore_other_sources(self, client, session, seeded) -> None:
        session.add(Item(item_id="777001", name="别的数据源物品", primary_class="gun"))
        session.add(
            CurrentPrice(
                item_id="777001",
                price=999,
                bl_today=10.0,
                source="delta",
                status=PriceStatus.OK.value,
                updated_at=ANCHOR,
            )
        )
        session.commit()

        body = client.get("/api/dashboard/summary").json()
        assert body["priced_count"] == 2
        assert body["rising_count"] == 1
