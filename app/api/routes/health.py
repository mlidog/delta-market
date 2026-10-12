"""健康检查。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.database import get_db
from app.scheduler import next_collect_at
from app.schemas import HealthOut
from app.utils import utcnow

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthOut, summary="健康检查")
def health(request: Request, db: Session = Depends(get_db)) -> HealthOut:
    """报告数据库连通性、当前数据源与调度器状态。"""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        database = "error"

    settings = get_settings()
    return HealthOut(
        status="ok" if database == "ok" else "degraded",
        app=settings.app_name,
        version=__version__,
        database=database,
        data_source=settings.data_source,
        # 调度器由 M5 接入，这里读取应用状态，未启动时为 False
        scheduler_running=bool(getattr(request.app.state, "scheduler_running", False)),
        next_collect_at=next_collect_at(getattr(request.app.state, "scheduler", None)),
        server_time=utcnow(),
    )
