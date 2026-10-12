"""M2 验证：数据源接口与 MockDataSource。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.data_sources import (
    DataSource,
    DataSourceAuthError,
    DataSourceError,
    DataSourceRateLimitError,
    DataSourceResponseError,
    DataSourceUnavailableError,
    ItemRecord,
    MockDataSource,
    create_data_source,
)
from app.data_sources.mock import MOCK_CATALOG

FIXED_NOW = datetime(2026, 10, 12, 14, 30, tzinfo=UTC).replace(tzinfo=None)


@pytest.fixture()
def source() -> MockDataSource:
    return MockDataSource(clock=lambda: FIXED_NOW)


class TestItemRecords:
    def test_catalog_is_loaded(self, source: MockDataSource) -> None:
        items = source.fetch_items()
        assert len(items) == len(MOCK_CATALOG) >= 20

    def test_item_ids_are_unique(self, source: MockDataSource) -> None:
        ids = [item.external_id for item in source.fetch_items()]
        assert len(ids) == len(set(ids))

    def test_required_fields_are_populated(self, source: MockDataSource) -> None:
        for item in source.fetch_items():
            assert item.external_id
            assert item.name
            assert item.primary_class
            assert item.grade is not None

    def test_catalog_covers_all_expected_categories(self, source: MockDataSource) -> None:
        categories = {item.primary_class for item in source.fetch_items()}
        assert {"gun", "ammo", "acc", "protect", "collection", "consume", "key"} <= categories

    def test_contains_untradable_items_for_filtering(self, source: MockDataSource) -> None:
        flags = {item.is_tradable for item in source.fetch_items()}
        assert flags == {True, False}

    def test_contains_worn_name_variant(self, source: MockDataSource) -> None:
        """真实数据里同名物品会带 "(几乎全新)" 之类的磨损度后缀。"""
        names = [item.name for item in source.fetch_items()]
        assert any("几乎全新" in name for name in names)

    def test_slot_area_helper(self) -> None:
        assert ItemRecord(external_id="1", name="x", slot_w=2, slot_h=3).slot_area == 6
        assert ItemRecord(external_id="1", name="x", slot_w=2).slot_area is None


class TestPriceRecords:
    def test_prices_skip_untradable_items(self, source: MockDataSource) -> None:
        tradable = {item.external_id for item in source.fetch_items() if item.is_tradable}
        prices = source.fetch_prices()
        assert {price.external_id for price in prices} == tradable
        assert len(prices) < len(MOCK_CATALOG)

    def test_prices_are_positive_integers(self, source: MockDataSource) -> None:
        for price in source.fetch_prices():
            assert isinstance(price.price, int)
            assert price.price > 0

    def test_same_moment_is_deterministic(self) -> None:
        first = MockDataSource(clock=lambda: FIXED_NOW).fetch_prices()
        second = MockDataSource(clock=lambda: FIXED_NOW).fetch_prices()
        assert first == second

    def test_different_moments_change_prices(self, source: MockDataSource) -> None:
        later = MockDataSource(clock=lambda: FIXED_NOW + timedelta(hours=6)).fetch_prices()
        before = {record.external_id: record.price for record in source.fetch_prices()}
        changed = [
            record for record in later if record.price != before[record.external_id]
        ]
        assert changed, "价格波动函数应当让价格随时间变化"

    def test_change_percentages_match_reference_prices(self, source: MockDataSource) -> None:
        for record in source.fetch_prices():
            assert record.bl_today == pytest.approx(
                (record.price - record.price_start) / record.price_start * 100, abs=0.01
            )
            assert record.day_7_bl == pytest.approx(
                (record.price - record.day_7_price) / record.day_7_price * 100, abs=0.01
            )
            assert record.day_30_bl == pytest.approx(
                (record.price - record.day_30_price) / record.day_30_price * 100, abs=0.01
            )

    def test_source_updated_at_is_not_in_the_future(self, source: MockDataSource) -> None:
        for record in source.fetch_prices():
            assert record.source_updated_at is not None
            assert record.source_updated_at <= FIXED_NOW

    def test_raw_payload_uses_platform_field_names(self, source: MockDataSource) -> None:
        raw = source.fetch_prices()[0].raw
        assert raw is not None
        assert {
            "id",
            "price",
            "price_start",
            "bl",
            "day_3_price",
            "day_7_bl",
            "day_30_bl",
            "is_get_time",
        } <= set(raw)

    def test_failure_injection_is_retryable_once_configured(self) -> None:
        source = MockDataSource(clock=lambda: FIXED_NOW, fail_first_n_calls=2)
        with pytest.raises(DataSourceUnavailableError):
            source.fetch_prices()
        with pytest.raises(DataSourceUnavailableError):
            source.fetch_prices()
        assert source.fetch_prices()


class TestErrorHierarchy:
    def test_unavailable_and_rate_limit_are_retryable(self) -> None:
        assert DataSourceUnavailableError.retryable is True
        assert DataSourceRateLimitError.retryable is True

    def test_auth_and_response_errors_are_not_retryable(self) -> None:
        assert DataSourceAuthError.retryable is False
        assert DataSourceResponseError.retryable is False

    def test_all_errors_derive_from_base(self) -> None:
        for error in (
            DataSourceUnavailableError,
            DataSourceRateLimitError,
            DataSourceAuthError,
            DataSourceResponseError,
        ):
            assert issubclass(error, DataSourceError)

    def test_rate_limit_carries_retry_after(self) -> None:
        error = DataSourceRateLimitError("too many requests", retry_after=30.0)
        assert error.retry_after == 30.0


class TestInterface:
    def test_datasource_cannot_be_instantiated_directly(self) -> None:
        with pytest.raises(TypeError):
            DataSource()  # type: ignore[abstract]

    def test_mock_source_satisfies_the_interface(self, source: MockDataSource) -> None:
        assert isinstance(source, DataSource)
        assert source.name == "mock"

    def test_context_manager_closes(self) -> None:
        with MockDataSource(clock=lambda: FIXED_NOW) as source:
            assert isinstance(source, MockDataSource)


class TestRegistry:
    def test_default_configuration_uses_mock(self) -> None:
        source = create_data_source(Settings(_env_file=None))
        assert isinstance(source, MockDataSource)
        assert source.name == "mock"

    def test_unknown_source_is_rejected(self) -> None:
        settings = Settings(_env_file=None, data_source="mock")
        object.__setattr__(settings, "data_source", "nope")
        with pytest.raises(DataSourceError):
            create_data_source(settings)

    def test_delta_source_is_not_available_before_m6(self) -> None:
        settings = Settings(_env_file=None, data_source="delta")
        with pytest.raises(ImportError):
            create_data_source(settings)
