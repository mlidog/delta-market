"""M6 验证：三角洲数据帝真实数据源。

用 `httpx.MockTransport` 拦截 HTTP，不联网、不消耗任何资源，
但走的是与生产完全相同的解析与错误映射代码路径。
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.data_sources import (
    DataSource,
    DataSourceAuthError,
    DataSourceRateLimitError,
    DataSourceResponseError,
    DataSourceUnavailableError,
    DeltaDataSource,
)

TOKEN = "test-token-0123456789abcdef"
BASE_URL = "https://example.invalid/workApi"

ITEMS_PAYLOAD = {
    "code": 0,
    "msg": "成功",
    "count": 2,
    "data": [
        {
            # 不可交易物品：oid 为 0，应被跳过
            "grade": 6,
            "id": 1,
            "is_get": 0,
            "length": 1,
            "objectID": 37150600001,
            "objectName": "6.8x51mm AP",
            "oid": 0,
            "pic": "https://playerhub.example/1.png",
            "primaryClass": "ammo",
            "secondClass": "ammo68",
            "secondClassCN": "ammo6.8x51",
            "width": 1,
        },
        {
            "grade": 3,
            "id": 322,
            "is_get": 1,
            "length": 1,
            "objectID": 13110000064,
            "objectName": "Cobra准直式瞄准镜",
            "oid": 9001,
            "pic": "https://playerhub.example/2.png",
            "primaryClass": "acc",
            "secondClass": "accScope",
            "secondClassCN": "瞄具",
            "width": 1,
        },
    ],
}

PRICES_PAYLOAD = {
    "code": 0,
    "msg": "成功",
    "count": 1,
    "data": [
        {
            "bl": -31.57,
            "day_30_bl": 16.34,
            "day_30_price": 22068,
            "day_3_bl": -29.64,
            "day_3_price": 36488,
            "day_7_bl": -29.64,
            "day_7_price": 36488,
            "id": 9001,
            "is_get_time": 1761911266,
            "price": 25673,
            "price_start": 25000,
            "tid": 898,
        }
    ],
}

MANUFACTURE_PAYLOAD = {
    "code": 0,
    "message": "成功",
    "msg": "成功",
    "data": [
        {
            "grade": 4,
            "id": 776,
            "isGet": 1,
            "is_pay": 1,
            "name": "OLIGHT WARRIOR 3S战术手电",
            "objectID": 13160000018,
            "oid": 0,
            "period": 4.5,
            "pic": "https://playerhub.example/3.png",
            "price": 16396,
            "priceMax": 71469,
            "price_hour": 3643,
            "primaryClass": "acc",
            "secondClass": "accFunctional",
            "secondClassCN": "功能性配件",
            "sxf": 2131,
            "unlockLevel": 1,
        }
    ],
}


def build_source(handler, **kwargs) -> DeltaDataSource:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DeltaDataSource(token=TOKEN, base_url=BASE_URL, client=client, **kwargs)


def json_handler(payload, captured: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(200, json=payload)

    return handler


class TestAuthentication:
    def test_missing_token_is_rejected_before_any_request(self) -> None:
        with pytest.raises(DataSourceAuthError):
            DeltaDataSource(token="", base_url=BASE_URL)

    def test_blank_token_is_rejected(self) -> None:
        with pytest.raises(DataSourceAuthError):
            DeltaDataSource(token="   ", base_url=BASE_URL)

    def test_token_is_sent_as_query_parameter(self) -> None:
        captured: list[httpx.Request] = []
        source = build_source(json_handler(PRICES_PAYLOAD, captured))
        source.fetch_prices()

        request = captured[0]
        assert request.url.params["token"] == TOKEN
        assert request.url.params["isZb"] == "0"
        assert request.headers["User-Agent"] == "DeltaForceApi/1.0"


class TestParsing:
    def test_items_parse_and_skip_untradable(self) -> None:
        source = build_source(json_handler(ITEMS_PAYLOAD))
        items = source.fetch_items()

        assert len(items) == 1  # oid=0 的不可交易物品被跳过
        item = items[0]
        assert item.external_id == "9001"
        assert item.name == "Cobra准直式瞄准镜"
        assert item.primary_class == "acc"
        assert item.second_class_cn == "瞄具"
        assert item.grade == 3
        assert item.is_tradable is True
        assert item.object_id == "13110000064"
        assert item.slot_area == 1

    def test_prices_parse_all_change_windows(self) -> None:
        source = build_source(json_handler(PRICES_PAYLOAD))
        prices = source.fetch_prices()

        assert len(prices) == 1
        price = prices[0]
        assert price.external_id == "9001"
        assert price.price == 25673
        assert price.price_start == 25000
        assert price.bl_today == pytest.approx(-31.57)
        assert price.day_30_bl == pytest.approx(16.34)
        assert price.source_updated_at == datetime.fromtimestamp(1761911266, UTC).replace(
            tzinfo=None
        )
        assert price.raw is not None and price.raw["tid"] == 898

    def test_manufacture_parses_profit_fields(self) -> None:
        source = build_source(json_handler(MANUFACTURE_PAYLOAD))
        records = source.fetch_manufacture(1, 3)

        assert len(records) == 1
        record = records[0]
        assert record.item_key == "13160000018"
        assert record.name == "OLIGHT WARRIOR 3S战术手电"
        assert record.station == "tech"
        assert record.unlock_level == 3
        assert record.period_hours == pytest.approx(4.5)
        assert record.profit == 16396
        assert record.profit_per_hour == 3643
        assert record.market_price == 71469
        assert record.fee == 2131
        assert record.origin == "pro"

    def test_profit_per_hour_is_derived_when_absent(self) -> None:
        payload = {
            "code": 0,
            "data": [
                {
                    "name": "测试物品",
                    "objectID": 123,
                    "period": 4,
                    "price": 1000,
                    "priceMax": 2000,
                    "primaryClass": "acc",
                }
            ],
        }
        source = build_source(json_handler(payload))
        record = source.fetch_manufacture(2, 1)[0]

        assert record.profit_per_hour == 250  # 1000 / 4
        assert record.unlock_level == 1
        assert record.origin == "pro"

    def test_station_key_mapping(self) -> None:
        source = build_source(json_handler(MANUFACTURE_PAYLOAD))
        assert source.fetch_manufacture(1, 1)[0].station == "tech"
        assert source.fetch_manufacture(2, 1)[0].station == "workbench"
        assert source.fetch_manufacture(3, 1)[0].station == "pharmacy"
        assert source.fetch_manufacture(4, 1)[0].station == "armor"

    def test_official_endpoint_is_marked_as_official(self) -> None:
        source = build_source(json_handler(MANUFACTURE_PAYLOAD))
        record = source.fetch_manufacture_official(1)[0]
        assert record.origin == "official"
        assert record.unlock_level == 0  # 官方接口不区分等级


class TestErrorMapping:
    def test_404_means_token_or_permission(self) -> None:
        source = build_source(lambda request: httpx.Response(404, json={"code": 404}))
        with pytest.raises(DataSourceAuthError):
            source.fetch_prices()

    def test_auth_error_is_not_retryable(self) -> None:
        assert DataSourceAuthError.retryable is False

    def test_business_error_code_is_a_response_error(self) -> None:
        source = build_source(json_handler({"code": 1001, "msg": "次数不足", "data": []}))
        with pytest.raises(DataSourceResponseError) as excinfo:
            source.fetch_prices()
        assert "次数不足" in str(excinfo.value)

    def test_server_error_is_retryable(self) -> None:
        source = build_source(lambda request: httpx.Response(503, text="bad gateway"))
        with pytest.raises(DataSourceUnavailableError):
            source.fetch_prices()

    def test_too_many_requests_carries_retry_after(self) -> None:
        source = build_source(
            lambda request: httpx.Response(429, headers={"Retry-After": "12"}, json={})
        )
        with pytest.raises(DataSourceRateLimitError) as excinfo:
            source.fetch_prices()
        assert excinfo.value.retry_after == 12.0

    def test_timeout_is_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        source = build_source(handler)
        with pytest.raises(DataSourceUnavailableError):
            source.fetch_prices()

    def test_network_error_is_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns failure")

        source = build_source(handler)
        with pytest.raises(DataSourceUnavailableError):
            source.fetch_items()

    def test_empty_item_list_is_reported_as_response_error(self) -> None:
        source = build_source(json_handler({"code": 0, "data": []}))
        with pytest.raises(DataSourceResponseError):
            source.fetch_items()

    def test_invalid_json_is_reported(self) -> None:
        source = build_source(lambda request: httpx.Response(200, text="<html>"))
        with pytest.raises(DataSourceResponseError):
            source.fetch_prices()


class TestInterface:
    def test_satisfies_the_datasource_interface(self) -> None:
        source = build_source(json_handler(PRICES_PAYLOAD))
        assert isinstance(source, DataSource)
        assert source.name == "delta"

    def test_external_client_is_not_closed(self) -> None:
        client = httpx.Client(transport=httpx.MockTransport(json_handler(PRICES_PAYLOAD)))
        source = DeltaDataSource(token=TOKEN, base_url=BASE_URL, client=client)
        source.close()
        # 自己创建的 client 才由自己关闭，外部传入的不能关
        assert client.is_closed is False
        client.close()

    def test_owned_client_is_closed(self) -> None:
        source = DeltaDataSource(token=TOKEN, base_url=BASE_URL)
        source.close()
        assert source._client.is_closed is True
