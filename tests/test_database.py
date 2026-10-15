"""M1 验证：配置解析与数据库表结构。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base, normalize_sqlite_url, settings
from app.models import CollectRun, CollectRunStatus, CurrentPrice, Item, PriceHistory, PriceStatus
from app.utils import utcnow

EXPECTED_TABLES = {"items", "current_price", "price_history", "collect_runs"}


@pytest.fixture()
def engine():
    """用内存库验证表结构，不碰真实的 data/app.db。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_all_tables_created(engine) -> None:
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_items_table_has_expected_columns(engine) -> None:
    columns = {col["name"] for col in inspect(engine).get_columns("items")}
    assert {
        "item_id",
        "name",
        "primary_class",
        "second_class",
        "second_class_cn",
        "grade",
        "pic_url",
        "is_tradable",
        "object_id",
        "slot_w",
        "slot_h",
        "created_at",
        "updated_at",
    } <= columns
    # 第二代 ID 已废弃，不应出现在表里
    assert "legacy_id" not in columns


def test_current_price_table_has_platform_change_columns(engine) -> None:
    columns = {col["name"] for col in inspect(engine).get_columns("current_price")}
    assert {
        "item_id",
        "price",
        "price_start",
        "bl_today",
        "day_3_price",
        "day_3_bl",
        "day_7_price",
        "day_7_bl",
        "day_30_price",
        "day_30_bl",
        "source_updated_at",
        "raw_json",
        "source",
        "updated_at",
        "status",
        "last_error",
        "consecutive_failures",
    } <= columns


def test_price_history_unique_constraint(engine) -> None:
    inspector = inspect(engine)
    constraints = inspector.get_unique_constraints("price_history")
    assert any(
        set(item["column_names"]) == {"item_id", "recorded_at"} for item in constraints
    )


def test_price_history_rejects_duplicate_snapshot(engine) -> None:
    """同一物品同一时刻的重复采集必须是幂等的（数据库层面拒绝重复）。"""
    stamp = utcnow()
    with Session(engine) as session:
        session.add(Item(item_id="322", name="Cobra准直式瞄准镜"))
        session.add(PriceHistory(item_id="322", price=100, recorded_at=stamp))
        session.commit()

    with Session(engine) as session:
        session.add(PriceHistory(item_id="322", price=200, recorded_at=stamp))
        with pytest.raises(IntegrityError):
            session.commit()


def test_relationships_roundtrip(engine) -> None:
    with Session(engine) as session:
        session.add(
            Item(
                item_id="322",
                name="Cobra准直式瞄准镜",
                primary_class="acc",
                second_class_cn="瞄具",
                grade=3,
                slot_w=1,
                slot_h=1,
            )
        )
        session.add(
            CurrentPrice(
                item_id="322",
                price=25673,
                price_start=25000,
                bl_today=-31.57,
                source="mock",
            )
        )
        session.add(PriceHistory(item_id="322", price=25673, source="mock"))
        session.add(CollectRun(source="mock", status=CollectRunStatus.SUCCESS.value, items_ok=1))
        session.commit()

        item = session.scalar(select(Item).where(Item.item_id == "322"))
        assert item is not None
        assert item.slot_area == 1

        current = session.scalar(select(CurrentPrice).where(CurrentPrice.item_id == "322"))
        assert current is not None
        assert current.price == 25673
        assert current.status == PriceStatus.OK.value
        assert current.is_stale is False

        history = session.scalars(select(PriceHistory)).all()
        assert len(history) == 1


def test_item_defaults_to_tradable_and_stamps_time(engine) -> None:
    with Session(engine) as session:
        session.add(Item(item_id="1", name="老式钢盔"))
        session.commit()
        item = session.scalar(select(Item))
        assert item is not None
        assert item.is_tradable is True
        assert item.created_at is not None
        assert item.updated_at is not None
        assert item.slot_area is None


class TestSettings:
    def test_cron_hours_parsed_from_comma_string(self) -> None:
        parsed = Settings(_env_file=None, collector_cron_hours="0,16,22")
        assert parsed.collector_cron_hours == [0, 16, 22]

    def test_cron_hours_accepts_full_width_comma_and_spaces(self) -> None:
        parsed = Settings(_env_file=None, collector_cron_hours=" 0， 16 ,22 ")
        assert parsed.collector_cron_hours == [0, 16, 22]

    def test_cron_hours_are_deduplicated_and_sorted(self) -> None:
        parsed = Settings(_env_file=None, collector_cron_hours="22,0,22,16")
        assert parsed.collector_cron_hours == [0, 16, 22]

    def test_cron_hours_rejects_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            Settings(_env_file=None, collector_cron_hours="24")

    def test_default_schedule_is_three_times_a_day(self) -> None:
        assert Settings(_env_file=None).collector_cron_hours == [0, 12, 22]

    def test_default_data_source_is_mock(self) -> None:
        assert Settings(_env_file=None).data_source == "mock"

    def test_token_is_not_leaked_in_repr(self) -> None:
        parsed = Settings(_env_file=None, delta_api_token="super-secret-token")
        assert "super-secret-token" not in repr(parsed)
        assert parsed.delta_api_token_value == "super-secret-token"


class TestDatabaseUrl:
    def test_relative_sqlite_path_is_anchored_to_project_root(self) -> None:
        normalized = normalize_sqlite_url("sqlite:///./data/app.db")
        assert normalized.endswith("/data/app.db")
        assert ":memory:" not in normalized

    def test_memory_url_is_untouched(self) -> None:
        assert normalize_sqlite_url("sqlite:///:memory:") == "sqlite:///:memory:"

    def test_postgres_url_is_untouched(self) -> None:
        url = "postgresql+psycopg://user:pass@localhost:5432/delta"
        assert normalize_sqlite_url(url) == url

    def test_active_settings_are_sqlite(self) -> None:
        assert settings.is_sqlite is True
