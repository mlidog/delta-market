"""M5 验证：定时采集调度。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.models import CollectRunStatus
from app.scheduler import (
    COLLECT_JOB_ID,
    MISFIRE_GRACE_SECONDS,
    STARTUP_JOB_ID,
    build_cron_trigger,
    create_scheduler,
    next_collect_at,
    run_collect_once,
)
from app.services import CollectResult

SHANGHAI = ZoneInfo("Asia/Shanghai")


def at(hour: int, minute: int = 0, day: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=SHANGHAI)


class StubCollector:
    """只实现 `run()` 的假采集器。"""

    def __init__(self, result: CollectResult | None = None, error: BaseException | None = None):
        self.result = result
        self.error = error
        self.calls = 0

    def run(self) -> CollectResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class TestCronTrigger:
    def test_next_fire_in_the_afternoon_is_22(self) -> None:
        trigger = build_cron_trigger(Settings(_env_file=None))
        assert trigger.get_next_fire_time(None, at(15)) == at(22)

    def test_next_fire_after_22_is_next_day_midnight(self) -> None:
        trigger = build_cron_trigger(Settings(_env_file=None))
        assert trigger.get_next_fire_time(None, at(23)) == at(0, day=13)

    def test_next_fire_after_midnight_is_12(self) -> None:
        trigger = build_cron_trigger(Settings(_env_file=None))
        assert trigger.get_next_fire_time(None, at(0, 30)) == at(12)

    def test_sequence_covers_the_three_slots(self) -> None:
        trigger = build_cron_trigger(Settings(_env_file=None))
        cursor = at(0, 1)
        fires = []
        for _ in range(3):
            cursor = trigger.get_next_fire_time(None, cursor)
            fires.append(cursor)
            # 触发时刻本身会被算作"下一个"，游标必须往前走一秒
            cursor += timedelta(seconds=1)
        assert fires == [at(12), at(22), at(0, day=13)]

    def test_custom_hours_are_respected(self) -> None:
        trigger = build_cron_trigger(
            Settings(_env_file=None, collector_cron_hours="3,9")
        )
        assert trigger.get_next_fire_time(None, at(1)) == at(3)
        assert trigger.get_next_fire_time(None, at(4)) == at(9)

    def test_trigger_uses_shanghai_timezone(self) -> None:
        trigger = build_cron_trigger(Settings(_env_file=None))
        assert str(trigger.timezone) == "Asia/Shanghai"
        # 北京时间 12:00 == UTC 04:00，验证时区没有退化成 UTC
        assert at(12).astimezone(ZoneInfo("UTC")).hour == 4


class TestCreateScheduler:
    def test_collect_job_is_registered_with_guards(self) -> None:
        scheduler = create_scheduler(
            Settings(_env_file=None, collector_run_on_startup=False)
        )
        job = scheduler.get_job(COLLECT_JOB_ID)
        assert job is not None
        assert job.max_instances == 1
        assert job.coalesce is True
        assert job.misfire_grace_time == MISFIRE_GRACE_SECONDS

    def test_startup_job_added_when_enabled(self) -> None:
        scheduler = create_scheduler(
            Settings(_env_file=None, collector_run_on_startup=True), now=at(10)
        )
        job = scheduler.get_job(STARTUP_JOB_ID)
        assert job is not None
        # 启动补采是一次性任务，触发时间就是传入的"当前时间"
        assert job.trigger.run_date == at(10)

    def test_startup_job_absent_when_disabled(self) -> None:
        scheduler = create_scheduler(
            Settings(_env_file=None, collector_run_on_startup=False)
        )
        assert scheduler.get_job(STARTUP_JOB_ID) is None

    def test_scheduler_timezone_comes_from_config(self) -> None:
        scheduler = create_scheduler(
            Settings(_env_file=None, collector_timezone="UTC")
        )
        assert str(scheduler.timezone) == "UTC"


class TestNextCollectAt:
    def test_none_without_scheduler(self) -> None:
        assert next_collect_at(None) is None

    def test_reports_upcoming_cron_slot(self) -> None:
        scheduler = create_scheduler(
            Settings(_env_file=None, collector_run_on_startup=False), job=lambda: None
        )
        scheduler.start()
        try:
            upcoming = next_collect_at(scheduler)
            assert upcoming is not None
            local = upcoming.astimezone(SHANGHAI)
            assert local.hour in (0, 12, 22)
            assert (local.minute, local.second) == (0, 0)
        finally:
            scheduler.shutdown(wait=False)


class TestRunCollectOnce:
    def test_returns_result_and_logs_success(self, caplog) -> None:
        collector = StubCollector(
            CollectResult(
                run_id=1,
                status=CollectRunStatus.SUCCESS,
                items_total=25,
                items_created=25,
                prices_written=23,
                history_written=23,
            )
        )
        with caplog.at_level(logging.INFO, logger="app.scheduler"):
            result = run_collect_once(collector)

        assert result is not None
        assert collector.calls == 1
        assert "采集完成" in caplog.text
        assert "status=success" in caplog.text

    def test_logs_failure_without_raising(self, caplog) -> None:
        collector = StubCollector(
            CollectResult(
                run_id=2,
                status=CollectRunStatus.FAILED,
                error="token 无效",
                retries=0,
            )
        )
        with caplog.at_level(logging.WARNING, logger="app.scheduler"):
            result = run_collect_once(collector)

        assert result is not None
        assert result.status is CollectRunStatus.FAILED
        assert "采集失败" in caplog.text
        assert "token 无效" in caplog.text

    def test_swallows_unexpected_exception(self, caplog) -> None:
        collector = StubCollector(error=RuntimeError("数据库炸了"))
        with caplog.at_level(logging.ERROR, logger="app.scheduler"):
            assert run_collect_once(collector) is None
        assert "采集任务异常终止" in caplog.text


class TestLifespanWiring:
    def test_health_reports_running_scheduler(
        self, monkeypatch, session_factory
    ) -> None:
        from app import main as main_module
        from app.database import get_db

        settings = Settings(
            _env_file=None,
            scheduler_enabled=True,
            collector_run_on_startup=False,
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: settings)
        # 建表由 M1 的独立测试覆盖，这里只验证调度器接线，避免碰真实数据库文件
        monkeypatch.setattr(main_module, "init_db", lambda: None)

        application = main_module.create_app()

        def _override_get_db():
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        application.dependency_overrides[get_db] = _override_get_db

        with TestClient(application) as client:
            body = client.get("/health").json()
            assert body["scheduler_running"] is True
            assert body["next_collect_at"] is not None
            assert application.state.scheduler_running is True

        # 退出上下文后调度器应已停止
        assert application.state.scheduler_running is False

    def test_scheduler_can_be_disabled(self, monkeypatch, session_factory) -> None:
        from app import main as main_module
        from app.database import get_db

        settings = Settings(_env_file=None, scheduler_enabled=False)
        monkeypatch.setattr(main_module, "get_settings", lambda: settings)
        monkeypatch.setattr(main_module, "init_db", lambda: None)

        application = main_module.create_app()

        def _override_get_db():
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        application.dependency_overrides[get_db] = _override_get_db

        with TestClient(application) as client:
            body = client.get("/health").json()
            assert body["scheduler_running"] is False
            assert body["next_collect_at"] is None


class TestConfigFlag:
    def test_scheduler_enabled_by_default(self) -> None:
        assert Settings(_env_file=None).scheduler_enabled is True

    def test_cron_hours_configurable(self) -> None:
        settings = Settings(_env_file=None, collector_cron_hours="1,13")
        assert settings.collector_cron_hours == [1, 13]

    def test_invalid_timezone_is_rejected(self) -> None:
        with pytest.raises(ZoneInfoNotFoundError):
            create_scheduler(Settings(_env_file=None, collector_timezone="Not/AZone"))
