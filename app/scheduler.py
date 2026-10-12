"""定时采集调度。

按配置的时区与时刻（默认北京时间 0 / 16 / 22 点）触发一次采集。

几点设计取舍：

* `max_instances=1`：采集宁可跳过一轮，也不能并发跑两轮——并发既会重复消耗平台资源，
  也会在 `price_history` 里留下同一时刻的重复快照。
* `coalesce=True` + `misfire_grace_time` 1 小时：笔记本休眠或进程重启导致错过触发时，
  只补跑一次，而不是把错过的每一轮都堆着补。
* 启动补采用一次性任务实现，而不是在 lifespan 里同步阻塞启动——
  全量采集要几秒到十几秒，不该卡住服务启动。
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings, get_settings
from app.services import Collector, CollectResult

logger = logging.getLogger(__name__)

COLLECT_JOB_ID = "collect-prices"
STARTUP_JOB_ID = "collect-prices-on-startup"

#: 错过触发后的补跑宽限期（秒）
MISFIRE_GRACE_SECONDS = 3600


def run_collect_once(collector: Collector | None = None) -> CollectResult | None:
    """执行一次采集并记录日志。

    故意吞掉异常：调度线程里抛出的异常只会变成日志里的一行堆栈，
    不如在这里显式记录，保证后续定时轮次不受影响。
    """
    try:
        result = (collector or Collector()).run()
    except Exception:
        logger.exception("采集任务异常终止")
        return None

    if result.ok:
        logger.info(
            "采集完成 status=%s 物品=%d/%d 价格=%d 快照=%d 标记=%d 重试=%d",
            result.status.value,
            result.items_total,
            result.items_created + result.items_updated,
            result.prices_written,
            result.history_written,
            result.stale_marked,
            result.retries,
        )
    else:
        logger.warning(
            "采集失败 status=%s 重试=%d 错误=%s",
            result.status.value,
            result.retries,
            result.error,
        )
    return result


def build_cron_trigger(settings: Settings | None = None) -> CronTrigger:
    """构造每日固定时刻触发的 Cron 触发器。"""
    config = settings or get_settings()
    return CronTrigger(
        hour=",".join(str(hour) for hour in config.collector_cron_hours),
        minute=0,
        timezone=ZoneInfo(config.collector_timezone),
    )


def create_scheduler(
    settings: Settings | None = None,
    *,
    job=run_collect_once,
    now: datetime | None = None,
) -> BackgroundScheduler:
    """创建（但尚未启动）采集调度器。"""
    config = settings or get_settings()
    timezone = ZoneInfo(config.collector_timezone)
    scheduler = BackgroundScheduler(timezone=timezone)

    scheduler.add_job(
        job,
        trigger=build_cron_trigger(config),
        id=COLLECT_JOB_ID,
        name="采集交易行价格",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
    )

    if config.collector_run_on_startup:
        scheduler.add_job(
            job,
            trigger="date",
            run_date=now or datetime.now(timezone),
            id=STARTUP_JOB_ID,
            name="启动补采",
            replace_existing=True,
            max_instances=1,
        )

    return scheduler


def next_collect_at(scheduler: BackgroundScheduler | None) -> datetime | None:
    """下一次定时采集时间；没有调度器或任务时返回 None。"""
    if scheduler is None:
        return None
    job = scheduler.get_job(COLLECT_JOB_ID)
    return job.next_run_time if job is not None else None
