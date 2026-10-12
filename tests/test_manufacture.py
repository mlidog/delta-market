"""M8 验证：特勤处制造收益同步与排行接口。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.api.deps import data_source_dependency
from app.data_sources import (
    STATION_KEYS,
    DataSource,
    DataSourceUnavailableError,
    ManufactureRecord,
    MockDataSource,
)
from app.models import ManufactureProfit
from app.services.manufacture import sync_manufacture

NOW = datetime(2026, 10, 12, 16, 0, tzinfo=UTC).replace(tzinfo=None)


class StubManufactureSource(DataSource):
    """只关心制造接口的桩数据源。"""

    name = "stub"

    def __init__(self, rows_per_call: int = 2, fail_stations: tuple[str, ...] = ()) -> None:
        self._rows = rows_per_call
        self._fail = set(fail_stations)
        self.calls: list[tuple[int, int]] = []

    def fetch_items(self):
        return []

    def fetch_prices(self):
        return []

    def fetch_manufacture(self, station_id: int, level: int) -> list[ManufactureRecord]:
        self.calls.append((station_id, level))
        station = STATION_KEYS[station_id]
        if station in self._fail:
            raise DataSourceUnavailableError(f"{station} 取数失败")
        return [self._record(station, level, index) for index in range(self._rows)]

    @staticmethod
    def _record(station: str, level: int, index: int) -> ManufactureRecord:
        profit = 1000 * level - index * 100
        period = 2.0 + index
        return ManufactureRecord(
            item_key=f"{station}-{level}-{index}",
            name=f"{station} 产物 {index}",
            station=station,
            unlock_level=level,
            period_hours=period,
            market_price=profit * 3,
            fee=profit // 10,
            profit=profit,
            profit_per_hour=round(profit / period),
            grade=4,
            primary_class="acc",
            second_class_cn="功能性配件",
            origin="pro",
            raw={"name": f"{station} 产物 {index}", "price": profit},
        )


# --------------------------------------------------------------------------- #
# 同步服务
# --------------------------------------------------------------------------- #
class TestSyncService:
    def test_writes_every_station_and_level(self, session) -> None:
        source = StubManufactureSource(rows_per_call=2)
        result = sync_manufacture(session, source, clock=lambda: NOW)

        assert result.ok is True
        assert result.requests == 12  # 4 站点 × 3 等级
        assert result.station_levels == 12
        assert result.rows == 24
        assert len(source.calls) == 12
        assert session.scalar(select(func.count()).select_from(ManufactureProfit)) == 24

    def test_resync_replaces_instead_of_duplicating(self, session) -> None:
        source = StubManufactureSource(rows_per_call=2)
        sync_manufacture(session, source, clock=lambda: NOW)
        second = sync_manufacture(session, source, clock=lambda: NOW)

        assert second.rows == 24
        assert session.scalar(select(func.count()).select_from(ManufactureProfit)) == 24

    def test_failing_station_does_not_block_others(self, session) -> None:
        source = StubManufactureSource(rows_per_call=1, fail_stations=("pharmacy",))
        result = sync_manufacture(session, source, clock=lambda: NOW)

        assert result.ok is False
        assert len(result.errors) == 3  # 三个等级都失败
        assert all("pharmacy" in message for message in result.errors)
        assert result.station_levels == 9
        assert session.scalar(select(func.count()).select_from(ManufactureProfit)) == 9

    def test_can_limit_to_one_station(self, session) -> None:
        source = StubManufactureSource(rows_per_call=3)
        result = sync_manufacture(session, source, stations=["tech"], clock=lambda: NOW)

        assert result.requests == 3
        assert result.rows == 9
        stations = set(session.scalars(select(ManufactureProfit.station)).all())
        assert stations == {"tech"}

    def test_unknown_station_is_reported(self, session) -> None:
        source = StubManufactureSource()
        result = sync_manufacture(session, source, stations=["nope"], clock=lambda: NOW)

        assert result.requests == 0
        assert any("未知站点" in message for message in result.errors)

    def test_works_with_the_mock_source(self, session) -> None:
        """模拟数据源也必须能跑通整条链路（离线开发的前提）。"""
        source = MockDataSource(clock=lambda: NOW)
        result = sync_manufacture(session, source, clock=lambda: NOW)

        assert result.requests == 12
        assert result.rows > 0
        assert session.scalar(select(func.count()).select_from(ManufactureProfit)) == result.rows
        # 模拟数据里刻意混了负收益，用来验证前端的亏损展示
        losses = session.scalar(
            select(func.count())
            .select_from(ManufactureProfit)
            .where(ManufactureProfit.profit < 0)
        )
        assert losses and losses > 0

    def test_records_source_name(self, session) -> None:
        sync_manufacture(session, StubManufactureSource(), stations=["tech"], clock=lambda: NOW)
        assert set(session.scalars(select(ManufactureProfit.source)).all()) == {"stub"}

    def test_sync_replaces_rows_from_another_source(self, session) -> None:
        """换数据源时旧榜单必须被清掉，否则 mock 与 delta 的数据会在排行里并列。"""
        session.add(
            ManufactureProfit(
                station="tech",
                unlock_level=1,
                item_key="old",
                name="旧数据源的行",
                origin="pro",
                source="mock",
                profit=1,
                fetched_at=NOW,
            )
        )
        session.commit()

        sync_manufacture(
            session, StubManufactureSource(rows_per_call=1), stations=["tech"], clock=lambda: NOW
        )

        assert set(session.scalars(select(ManufactureProfit.source)).all()) == {"stub"}
        assert session.scalar(select(func.count()).select_from(ManufactureProfit)) == 3


# --------------------------------------------------------------------------- #
# 排行接口
# --------------------------------------------------------------------------- #
@pytest.fixture()
def manufacture_rows(session):
    """三档收益 + 一条空值 + 一条官方口径，用于验证排序与筛选。"""
    rows = [
        ManufactureProfit(
            station="tech",
            unlock_level=1,
            item_key="a",
            name="高总收益",
            origin="pro",
            source="mock",
            period_hours=8.0,
            profit=90000,
            profit_per_hour=11250,
            market_price=120000,
            fee=3000,
            fetched_at=NOW,
        ),
        ManufactureProfit(
            station="tech",
            unlock_level=2,
            item_key="b",
            name="高时薪低总收益",
            origin="pro",
            source="mock",
            period_hours=1.0,
            profit=5000,
            profit_per_hour=5000,
            market_price=20000,
            fee=600,
            fetched_at=NOW,
        ),
        ManufactureProfit(
            station="workbench",
            unlock_level=1,
            item_key="c",
            name="亏损品",
            origin="pro",
            source="mock",
            period_hours=2.0,
            profit=-3000,
            profit_per_hour=-1500,
            fetched_at=NOW,
        ),
        ManufactureProfit(
            station="workbench",
            unlock_level=1,
            item_key="d",
            name="缺数据",
            origin="pro",
            source="mock",
            period_hours=None,
            profit=None,
            profit_per_hour=None,
            fetched_at=NOW,
        ),
        ManufactureProfit(
            station="armor",
            unlock_level=1,
            item_key="e",
            name="官方口径",
            origin="official",
            source="mock",
            period_hours=3.0,
            profit=99999,
            profit_per_hour=33333,
            fetched_at=NOW,
        ),
    ]
    session.add_all(rows)
    session.commit()
    return session


def get_rows(client, **params) -> dict:
    response = client.get("/api/manufacture", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def get_groups(client, **params) -> dict:
    response = client.get("/api/manufacture/by-station", params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def multi_level_rows(session):
    """同一个产物在 L1/L2/L3 各出现一次。"""
    for level, profit in ((1, 100), (2, 200), (3, 300)):
        session.add(
            ManufactureProfit(
                station="tech",
                unlock_level=level,
                item_key="same-item",
                name="跨等级产物",
                origin="pro",
                source="mock",
                period_hours=4.0 + level,
                profit=profit,
                profit_per_hour=profit // 4,
                fetched_at=NOW,
            )
        )
    session.add(
        ManufactureProfit(
            station="tech",
            unlock_level=1,
            item_key="only-one",
            name="单等级产物",
            origin="pro",
            source="mock",
            profit=50,
            profit_per_hour=50,
            fetched_at=NOW,
        )
    )
    session.commit()
    return session


class TestLevelDeduplication:
    """同一物品在多个等级出现时，只留等级最高的那条。"""

    def test_duplicate_item_keeps_only_the_highest_level(
        self, client, multi_level_rows
    ) -> None:
        body = get_groups(client)
        tech = next(group for group in body["groups"] if group["station"] == "tech")
        rows = {item["name"]: item for item in tech["items"]}

        assert rows["跨等级产物"]["unlock_level"] == 3
        assert rows["跨等级产物"]["profit"] == 300
        assert tech["total"] == 2  # 跨等级产物只算一条

    def test_flat_endpoint_dedupes_too(self, client, multi_level_rows) -> None:
        body = get_rows(client, sort="profit", order="desc")
        assert body["total"] == 2
        levels = {item["name"]: item["unlock_level"] for item in body["items"]}
        assert levels["跨等级产物"] == 3

    def test_level_filter_can_still_target_one_level(
        self, client, multi_level_rows
    ) -> None:
        body = get_rows(client, level=2)
        assert body["total"] == 1
        assert body["items"][0]["unlock_level"] == 2
        assert body["items"][0]["profit"] == 200

    def test_other_stations_are_unaffected(self, client, multi_level_rows) -> None:
        body = get_groups(client)
        workbench = next(
            group for group in body["groups"] if group["station"] == "workbench"
        )
        assert workbench["total"] == 0


class TestManufactureByStation:
    """站点分组的排行：四个站点各排各的。"""

    def test_groups_cover_all_four_stations(self, client, manufacture_rows) -> None:
        body = get_groups(client)
        assert [group["station"] for group in body["groups"]] == [
            "tech",
            "workbench",
            "pharmacy",
            "armor",
        ]
        assert [group["label"] for group in body["groups"]] == [
            "技术中心",
            "工作台",
            "制药台",
            "防具台",
        ]

    def test_each_station_is_ranked_independently(self, client, manufacture_rows) -> None:
        body = get_groups(client, sort="profit", order="desc")
        tech = next(group for group in body["groups"] if group["station"] == "tech")
        assert tech["total"] == 2
        assert [item["name"] for item in tech["items"]] == ["高总收益", "高时薪低总收益"]

    def test_nulls_stay_last_inside_a_group(self, client, manufacture_rows) -> None:
        body = get_groups(client, sort="profit", order="desc")
        workbench = next(group for group in body["groups"] if group["station"] == "workbench")
        assert [item["name"] for item in workbench["items"]] == ["亏损品", "缺数据"]

    def test_station_without_matching_data_returns_empty_group(
        self, client, manufacture_rows
    ) -> None:
        # 夹具里的 armor 只有官方口径的行，不属于 pro
        body = get_groups(client)
        armor = next(group for group in body["groups"] if group["station"] == "armor")
        assert armor["total"] == 0
        assert armor["items"] == []

    def test_level_filter_applies_to_every_group(self, client, manufacture_rows) -> None:
        body = get_groups(client, level=2)
        tech = next(group for group in body["groups"] if group["station"] == "tech")
        assert [item["name"] for item in tech["items"]] == ["高时薪低总收益"]
        workbench = next(group for group in body["groups"] if group["station"] == "workbench")
        assert workbench["total"] == 0

    def test_per_station_limits_rows(self, client, manufacture_rows) -> None:
        body = get_groups(client, per_station=1, sort="profit", order="desc")
        tech = next(group for group in body["groups"] if group["station"] == "tech")
        assert tech["total"] == 2
        assert len(tech["items"]) == 1
        assert body["per_station"] == 1

    def test_default_sort_is_hourly_profit(self, client, manufacture_rows) -> None:
        body = get_groups(client)
        assert body["sort"] == "profit_per_hour"
        tech = next(group for group in body["groups"] if group["station"] == "tech")
        assert [item["name"] for item in tech["items"]] == ["高总收益", "高时薪低总收益"]

    def test_metadata_is_reported(self, client, manufacture_rows) -> None:
        body = get_groups(client, sort="profit", order="asc")
        assert body["order"] == "asc"
        assert body["origin"] == "pro"
        assert body["source"] == "mock"
        assert body["levels"] == [1, 2, 3]
        assert body["fetched_at"].endswith("Z")

    def test_response_does_not_expose_material_cost(self, client, manufacture_rows) -> None:
        tech = next(
            group for group in get_groups(client)["groups"] if group["station"] == "tech"
        )
        assert "implied_material_cost" not in tech["items"][0]

    def test_invalid_per_station_is_rejected(self, client, manufacture_rows) -> None:
        response = client.get("/api/manufacture/by-station", params={"per_station": 999})
        assert response.status_code == 422


class TestManufactureApi:
    def test_default_ranks_by_hourly_profit(self, client, manufacture_rows) -> None:
        body = get_rows(client)
        assert body["origin"] == "pro"
        assert body["total"] == 4  # 官方口径那条被排除
        assert [item["name"] for item in body["items"]][:3] == [
            "高总收益",
            "高时薪低总收益",
            "亏损品",
        ]

    def test_sort_by_total_profit(self, client, manufacture_rows) -> None:
        body = get_rows(client, sort="profit", order="desc")
        assert [item["name"] for item in body["items"]][:2] == ["高总收益", "高时薪低总收益"]

    def test_ascending_order_puts_losses_first(self, client, manufacture_rows) -> None:
        body = get_rows(client, sort="profit", order="asc")
        assert body["items"][0]["name"] == "亏损品"

    def test_missing_values_are_last_in_both_directions(self, client, manufacture_rows) -> None:
        assert get_rows(client, sort="profit", order="desc")["items"][-1]["name"] == "缺数据"
        assert get_rows(client, sort="profit", order="asc")["items"][-1]["name"] == "缺数据"

    def test_filter_by_station(self, client, manufacture_rows) -> None:
        body = get_rows(client, station="workbench")
        assert body["total"] == 2
        assert {item["station"] for item in body["items"]} == {"workbench"}

    def test_filter_by_level(self, client, manufacture_rows) -> None:
        body = get_rows(client, level=2)
        assert body["total"] == 1
        assert body["items"][0]["name"] == "高时薪低总收益"

    def test_official_origin_can_be_requested(self, client, manufacture_rows) -> None:
        body = get_rows(client, origin="official")
        assert body["total"] == 1
        assert body["items"][0]["name"] == "官方口径"

    def test_pagination(self, client, manufacture_rows) -> None:
        page = get_rows(client, limit=2, offset=1)
        assert page["total"] == 4
        assert len(page["items"]) == 2

    def test_limit_is_capped(self, client, manufacture_rows) -> None:
        assert client.get("/api/manufacture", params={"limit": 999}).status_code == 422

    def test_unknown_sort_field_is_rejected(self, client, manufacture_rows) -> None:
        assert client.get("/api/manufacture", params={"sort": "nope"}).status_code == 422

    def test_response_carries_station_metadata_and_timestamp(
        self, client, manufacture_rows
    ) -> None:
        body = get_rows(client)
        assert body["source"] == "mock"
        assert [station["key"] for station in body["stations"]] == [
            "tech",
            "workbench",
            "pharmacy",
            "armor",
        ]
        assert body["stations"][0]["label"] == "技术中心"
        assert body["levels"] == [1, 2, 3]
        assert body["fetched_at"].endswith("Z")

    def test_item_labels_and_percentages_are_shaped_for_the_frontend(
        self, client, manufacture_rows
    ) -> None:
        item = get_rows(client, station="tech", level=1)["items"][0]
        assert item["station_label"] == "技术中心"
        assert item["period_hours"] == pytest.approx(8.0)
        assert item["profit"] == 90000
        assert item["profit_per_hour"] == 11250
        assert item["fetched_at"].endswith("Z")

    def test_rows_from_other_sources_are_hidden(self, client, session, manufacture_rows) -> None:
        session.add(
            ManufactureProfit(
                station="tech",
                unlock_level=1,
                item_key="other",
                name="别家数据源的行",
                origin="pro",
                source="delta",
                profit=123456,
                fetched_at=NOW,
            )
        )
        session.commit()

        body = get_rows(client, sort="profit", order="desc")
        assert all(item["name"] != "别家数据源的行" for item in body["items"])
        assert body["items"][0]["name"] == "高总收益"

    def test_source_can_be_requested_explicitly(self, client, session, manufacture_rows) -> None:
        session.add(
            ManufactureProfit(
                station="tech",
                unlock_level=1,
                item_key="other",
                name="别家数据源的行",
                origin="pro",
                source="delta",
                profit=123456,
                fetched_at=NOW,
            )
        )
        session.commit()

        body = get_rows(client, source="delta")
        assert body["total"] == 1
        assert body["source"] == "delta"
        assert body["items"][0]["name"] == "别家数据源的行"

    def test_empty_result_is_returned_cleanly(self, client) -> None:
        body = get_rows(client)
        assert body["items"] == []
        assert body["total"] == 0
        assert body["fetched_at"] is None


class TestManualSyncEndpoint:
    def test_sync_uses_the_injected_data_source(self, client, session) -> None:
        stub = StubManufactureSource(rows_per_call=1)
        client.app.dependency_overrides[data_source_dependency] = lambda: stub

        response = client.post("/api/manufacture/sync")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["requests"] == 12
        assert body["station_levels"] == 12
        assert body["rows"] == 12
        assert body["errors"] == []
        assert body["started_at"].endswith("Z")
        assert len(stub.calls) == 12

    def test_sync_can_target_one_station(self, client, session) -> None:
        stub = StubManufactureSource(rows_per_call=2)
        client.app.dependency_overrides[data_source_dependency] = lambda: stub

        body = client.post("/api/manufacture/sync", params={"station": "armor"}).json()
        assert body["requests"] == 3
        assert body["rows"] == 6

    def test_sync_reports_partial_failure(self, client, session) -> None:
        stub = StubManufactureSource(rows_per_call=1, fail_stations=("armor",))
        client.app.dependency_overrides[data_source_dependency] = lambda: stub

        body = client.post("/api/manufacture/sync").json()
        assert len(body["errors"]) == 3
        assert body["station_levels"] == 9

    def test_synced_data_is_immediately_queryable(self, client, session) -> None:
        stub = StubManufactureSource(rows_per_call=2)
        client.app.dependency_overrides[data_source_dependency] = lambda: stub
        client.post("/api/manufacture/sync")

        body = get_rows(client, sort="profit", order="desc")
        assert body["total"] == 24
        assert body["items"][0]["profit"] == 3000  # level=3 的最高值
        # 当前配置的数据源是 mock，库里只有 stub 的数据 → 回退展示并在响应里说明来源
        assert body["source"] == "stub"
