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
from app.services import Collector, CollectResult, publish_site_data
from app.services.manufacture import ManufactureSyncResult, sync_manufacture

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


def run_manufacture_sync() -> ManufactureSyncResult | None:
    """同步特勤处制造收益（每个站点×等级消耗 1 次资源，完整同步 12 次）。"""
    from app.data_sources import create_data_source
    from app.database import SessionLocal

    source = create_data_source()
    session = SessionLocal()
    try:
        result = sync_manufacture(session, source)
    except Exception:
        logger.exception("制造收益同步异常终止")
        return None
    finally:
        session.close()
        source.close()

    if result.ok:
        logger.info(
            "制造收益同步完成 记录=%d 请求=%d 组合=%d",
            result.rows,
            result.requests,
            result.station_levels,
        )
    else:
        logger.warning(
            "制造收益同步部分失败 记录=%d 请求=%d 错误=%s",
            result.rows,
            result.requests,
            "；".join(result.errors),
        )
    return result


def run_pipeline() -> None:
    """一轮完整的例行任务：采集价格 → 同步制造收益 → 导出并发布静态站。

    三步串在一个任务里，而不是拆成三个 job，是为了保证顺序：
    导出必须发生在采集和同步之后，发布又要发生在导出之后。
    """
    collect_result = run_collect_once()
    run_manufacture_sync()
    published = publish_site_data()

    if published.skipped:
        logger.info("未配置远端仓库，跳过发布静态数据")
    elif published.ok:
        logger.info(
            "静态数据已发布：提交=%s 推送=%s%s 采集=%s",
            published.committed,
            published.pushed,
            "（走系统代理）" if published.used_proxy else "",
            collect_result.status.value if collect_result else "unknown",
        )
    else:
        logger.warning("静态数据发布失败：%s", published.error)


def build_cron_trigger(settings: Settings | None = None) -> CronTrigger:
    """构造每日固定时刻触发的 Cron 触发器。

    分钟取 `COLLECTOR_CRON_MINUTE`（默认 15）：0 点的补货价在接口上要过几分钟才出现，
    整点采到的是补货前的高价（详见 `app/config.py` 里该字段的说明）。
    """
    config = settings or get_settings()
    return CronTrigger(
        hour=",".join(str(hour) for hour in config.collector_cron_hours),
        minute=config.collector_cron_minute,
        timezone=ZoneInfo(config.collector_timezone),
    )


def create_scheduler(
    settings: Settings | None = None,
    *,
    job=run_pipeline,
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
        name="采集并发布行情数据",
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
            name="启动补采并发布",
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
