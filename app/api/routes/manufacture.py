"""特勤处制造收益排行。"""

from __future__ import annotations

from enum import StrEnum

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import data_source_dependency
from app.config import get_settings
from app.data_sources import STATION_IDS, STATION_KEYS, STATION_NAMES, DataSource
from app.database import get_db
from app.models import ManufactureProfit
from app.schemas import (
    ManufactureGroupedOut,
    ManufactureItemOut,
    ManufactureListOut,
    ManufactureStationGroupOut,
    ManufactureStationOut,
    ManufactureSyncOut,
)
from app.services.manufacture import DEFAULT_LEVELS, sync_manufacture

router = APIRouter(tags=["manufacture"])


class ManufactureSort(StrEnum):
    """全部排序字段都在同一张表上，所以排序直接交给 SQL。"""

    profit = "profit"
    profit_per_hour = "profit_per_hour"
    period_hours = "period_hours"
    market_price = "market_price"
    name = "name"
    grade = "grade"


class SortOrder(StrEnum):
    asc = "asc"
    desc = "desc"


@router.get("/manufacture", response_model=ManufactureListOut, summary="特勤处制造收益（平铺）")
def list_manufacture(
    station: str | None = Query(None, description="站点：tech / workbench / pharmacy / armor"),
    level: int | None = Query(None, ge=0, le=3, description="部门等级 1~3"),
    origin: str = Query("pro", description="pro=自有源计算，official=官方数据"),
    source: str | None = Query(None, description="数据来源，默认取当前配置的数据源"),
    sort: ManufactureSort = Query(ManufactureSort.profit_per_hour, description="排序字段"),
    order: SortOrder = Query(SortOrder.desc),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ManufactureListOut:
    """跨站点平铺的排行榜。

    * `profit`（总收益）：适合"我一天只上线一次，把产能用满"
    * `profit_per_hour`（每小时收益）：适合"我频繁上线，产线不该停"
    """
    filters, active_source = _resolve_filters(
        db, origin=origin, source=source, station=station, level=level
    )
    total = _count(db, filters)

    rows = db.scalars(
        select(ManufactureProfit)
        .where(*filters)
        .order_by(_ordering(sort, order), ManufactureProfit.name.asc())
        .limit(limit)
        .offset(offset)
    ).all()

    return ManufactureListOut(
        items=[_to_out(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        stations=_stations(),
        levels=list(DEFAULT_LEVELS),
        origin=origin,
        source=active_source,
        fetched_at=db.scalar(select(func.max(ManufactureProfit.fetched_at)).where(*filters)),
    )


@router.get(
    "/manufacture/by-station",
    response_model=ManufactureGroupedOut,
    summary="特勤处制造收益（按站点分组）",
)
def list_manufacture_by_station(
    level: int | None = Query(None, ge=0, le=3, description="部门等级 1~3"),
    origin: str = Query("pro", description="pro=自有源计算，official=官方数据"),
    source: str | None = Query(None, description="数据来源，默认取当前配置的数据源"),
    sort: ManufactureSort = Query(ManufactureSort.profit_per_hour, description="站点内排序字段"),
    order: SortOrder = Query(SortOrder.desc),
    per_station: int = Query(10, ge=1, le=50, description="每个站点返回的条目上限"),
    db: Session = Depends(get_db),
) -> ManufactureGroupedOut:
    """四个站点各自一张榜，互不干扰。

    站点的解锁进度与产线数量都不一样，混在一起排的意义有限；
    分开看才方便回答"我这个站点现在做什么最划算"。
    """
    filters, active_source = _resolve_filters(
        db, origin=origin, source=source, level=level
    )
    ordering = _ordering(sort, order)

    groups: list[ManufactureStationGroupOut] = []
    for key, station_id in STATION_IDS.items():
        station_filters = [*filters, ManufactureProfit.station == key]
        rows = db.scalars(
            select(ManufactureProfit)
            .where(*station_filters)
            .order_by(ordering, ManufactureProfit.name.asc())
            .limit(per_station)
        ).all()
        groups.append(
            ManufactureStationGroupOut(
                station=key,
                label=STATION_NAMES.get(station_id, key),
                station_id=station_id,
                total=_count(db, station_filters),
                items=[_to_out(row) for row in rows],
            )
        )

    return ManufactureGroupedOut(
        groups=groups,
        levels=list(DEFAULT_LEVELS),
        origin=origin,
        source=active_source,
        sort=sort.value,
        order=order.value,
        per_station=per_station,
        fetched_at=db.scalar(select(func.max(ManufactureProfit.fetched_at)).where(*filters)),
    )


@router.post("/manufacture/sync", response_model=ManufactureSyncOut, summary="立即同步制造收益")
def sync_now(
    station: list[str] | None = Query(None, description="只同步指定站点，可重复传"),
    db: Session = Depends(get_db),
    source: DataSource = Depends(data_source_dependency),
) -> ManufactureSyncOut:
    """手动触发一次同步。

    ⚠️ 这会**真实消耗平台资源**：每个（站点 × 等级）计 1 次资源，
    完整同步 4 站点 × 3 等级 = 12 次。
    """
    result = sync_manufacture(db, source, stations=station)
    return ManufactureSyncOut(
        rows=result.rows,
        requests=result.requests,
        station_levels=result.station_levels,
        errors=result.errors,
        started_at=result.started_at,
        finished_at=result.finished_at,
    )


# --------------------------------------------------------------------------- #
# 内部辅助
# --------------------------------------------------------------------------- #
def _stations() -> list[ManufactureStationOut]:
    return [
        ManufactureStationOut(
            key=key,
            label=STATION_NAMES.get(STATION_IDS[key], key),
            station_id=STATION_IDS[key],
        )
        for key in STATION_KEYS.values()
    ]


def _ordering(sort: ManufactureSort, order: SortOrder):
    """排序表达式：空值永远排在最后，避免"缺数据"占据榜首。"""
    column = getattr(ManufactureProfit, sort.value)
    return column.asc().nullslast() if order is SortOrder.asc else column.desc().nullslast()


def _resolve_filters(
    db: Session,
    *,
    origin: str,
    source: str | None,
    station: str | None = None,
    level: int | None = None,
) -> tuple[list, str]:
    """组装筛选条件，并处理"当前数据源还没有榜单"的过渡态。

    典型场景：刚把 `DATA_SOURCE` 从 mock 切到 delta（或反过来），
    库里只有另一个数据源的数据。此时回退展示已有数据，并在响应里如实报告来源，
    而不是甩给用户一个空排行榜。
    """
    active_source = source or get_settings().data_source
    base_filters: list = [ManufactureProfit.origin == origin]
    if station:
        base_filters.append(ManufactureProfit.station == station)
    if level is not None:
        base_filters.append(ManufactureProfit.unlock_level == level)

    filters = [*base_filters, ManufactureProfit.source == active_source]
    if source is None and _count(db, filters) == 0 and _count(db, base_filters) > 0:
        fallback = db.scalar(
            select(ManufactureProfit.source).where(*base_filters).limit(1)
        )
        return base_filters, fallback or active_source
    return filters, active_source


def _count(db: Session, filters: list) -> int:
    return int(
        db.scalar(select(func.count()).select_from(ManufactureProfit).where(*filters)) or 0
    )


def _to_out(row: ManufactureProfit) -> ManufactureItemOut:
    return ManufactureItemOut(
        item_key=row.item_key,
        name=row.name,
        station=row.station,
        station_label=STATION_NAMES.get(STATION_IDS.get(row.station, 0), row.station),
        unlock_level=row.unlock_level,
        grade=row.grade,
        category=row.primary_class,
        sub_category=row.second_class_cn,
        pic_url=row.pic_url,
        period_hours=row.period_hours,
        market_price=row.market_price,
        fee=row.fee,
        profit=row.profit,
        profit_per_hour=row.profit_per_hour,
        origin=row.origin,
        fetched_at=row.fetched_at,
    )
