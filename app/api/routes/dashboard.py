"""看板摘要。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import CollectRun, CurrentPrice, Item, PriceStatus
from app.schemas import CollectRunOut, DashboardSummaryOut
from app.utils import utcnow

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", response_model=DashboardSummaryOut, summary="看板摘要")
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummaryOut:
    """物品总数、涨跌家数与最近一次采集状态。"""
    return DashboardSummaryOut(
        item_count=_count(db, select(func.count()).select_from(Item)),
        tradable_count=_count(
            db, select(func.count()).select_from(Item).where(Item.is_tradable.is_(True))
        ),
        priced_count=_count(
            db,
            select(func.count())
            .select_from(CurrentPrice)
            .where(CurrentPrice.price.is_not(None)),
        ),
        # 涨跌家数用平台自带的"今日涨跌"口径，它不依赖我们的历史积累，第一天就有数据
        rising_count=_count(
            db,
            select(func.count())
            .select_from(CurrentPrice)
            .where(CurrentPrice.bl_today > 0),
        ),
        falling_count=_count(
            db,
            select(func.count())
            .select_from(CurrentPrice)
            .where(CurrentPrice.bl_today < 0),
        ),
        flat_count=_count(
            db,
            select(func.count())
            .select_from(CurrentPrice)
            .where(CurrentPrice.bl_today == 0),
        ),
        stale_count=_count(
            db,
            select(func.count())
            .select_from(CurrentPrice)
            .where(CurrentPrice.status == PriceStatus.STALE.value),
        ),
        data_source=get_settings().data_source,
        last_collect=_last_collect(db),
        generated_at=utcnow(),
    )


def _count(db: Session, statement) -> int:
    return int(db.scalar(statement) or 0)


def _last_collect(db: Session) -> CollectRunOut | None:
    run = db.scalar(select(CollectRun).order_by(CollectRun.id.desc()).limit(1))
    if run is None:
        return None
    return CollectRunOut(
        id=run.id,
        source=run.source,
        status=run.status,
        items_ok=run.items_ok,
        items_failed=run.items_failed,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
    )
