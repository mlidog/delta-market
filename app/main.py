"""FastAPI 应用装配。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import dashboard, health, items
from app.config import get_settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时确保表结构存在；调度器在 M5 接入。"""
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
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
