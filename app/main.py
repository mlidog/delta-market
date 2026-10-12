"""FastAPI 应用装配。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import dashboard, health, items
from app.config import get_settings
from app.database import init_db
from app.scheduler import create_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时建表并（可选）启动采集调度器，关闭时优雅停止。"""
    init_db()
    settings = get_settings()
    scheduler = None

    if settings.scheduler_enabled:
        scheduler = create_scheduler(settings)
        scheduler.start()
        app.state.scheduler = scheduler
        app.state.scheduler_running = True
        logger.info(
            "采集调度器已启动 时区=%s 时刻=%s 启动补采=%s",
            settings.collector_timezone,
            settings.collector_cron_hours,
            settings.collector_run_on_startup,
        )

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            app.state.scheduler_running = False
            logger.info("采集调度器已停止")


def create_app() -> FastAPI:
    settings = get_settings()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=settings.log_level.upper())

    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "《三角洲行动》交易行物价观察工具后端。"
            "数据来源：三角洲数据帝（可通过 DATA_SOURCE 切换为本地模拟数据）。"
        ),
        lifespan=lifespan,
    )
    application.include_router(health.router)
    application.include_router(items.router, prefix="/api")
    application.include_router(dashboard.router, prefix="/api")
    return application


app = create_app()
