"""物品列表与历史价格。"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import CurrentPrice, Item, PriceHistory
from app.schemas import ItemHistoryOut, ItemListOut, ItemPriceOut, PricePointOut
from app.services.pricing import (
    PriceChange,
    SpreadStats,
    change_pct,
    load_price_changes,
    load_spread_stats,
)
from app.utils import utcnow

router = APIRouter(tags=["items"])

#: 历史曲线的可选时间窗
HISTORY_PERIODS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class SortField(StrEnum):
    """支持的排序字段。"""

    name = "name"
    price = "price"
    grade = "grade"
    price_per_slot = "price_per_slot"
    bl_today = "bl_today"
    day_3_bl = "day_3_bl"
    day_7_bl = "day_7_bl"
    day_30_bl = "day_30_bl"
    change_prev_pct = "change_prev_pct"
    change_24h_pct = "change_24h_pct"
    change_7d_pct = "change_7d_pct"
    #: 今日价格变动的绝对值（数值差距，不是百分比）
    price_delta = "price_delta"
    #: 24 小时最高价与补货价的价差（看"抢补货"机会）
    spread_24h = "spread_24h"


class SortOrder(StrEnum):
    asc = "asc"
    desc = "desc"


#: 涨幅排行里挪到最后的分类：找行情时收集品与钥匙卡噪声太大。
#: 数据帝把这两类放在 props 兜底分类下，以**二级分类代码**为准（collection / key）。
#: 中文名也一并兼容——实测钥匙卡的中文名是"钥匙"而不是"钥匙卡"，
#: 光靠名字判断会漏。
DEPRIORITIZED_SUB_CATEGORIES = frozenset(
    {"collection", "key", "收集品", "钥匙", "钥匙卡"}
)

#: 这些排序字段属于"涨幅排行"，会应用上面的降权规则；
#: 按价格、单格价值、名称排序时不降权——那时用户要的就是全量排序。
CHANGE_SORT_FIELDS = frozenset(
    {
        SortField.bl_today,
        SortField.day_3_bl,
        SortField.day_7_bl,
        SortField.day_30_bl,
        SortField.change_prev_pct,
        SortField.change_24h_pct,
        SortField.change_7d_pct,
    }
)


@router.get("/items", response_model=ItemListOut, summary="物品列表")
def list_items(
    category: str | None = Query(None, description="一级分类，如 ammo / acc / gun / collection"),
    sub_category: str | None = Query(None, description="二级分类中文名，如 瞄具 / 胸挂"),
    search: str | None = Query(None, description="按名称模糊搜索（覆盖全部物品，不只是当前页）"),
    grade: int | None = Query(None, ge=0, le=6, description="物品等级 0~6"),
    tradable: bool | None = Query(None, description="是否只看可在交易行交易的物品"),
    sort: SortField = Query(SortField.price, description="排序字段"),
    order: SortOrder = Query(SortOrder.desc, description="排序方向"),
    limit: int = Query(50, ge=1, le=200, description="每页数量，上限 200"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> ItemListOut:
    """按分类筛选、排序并分页返回物品及其当前价与涨跌幅。

    排序在内存中完成：派生涨跌幅（`change_*_pct`）来自历史快照聚合，
    无法用一次 SQL 排序覆盖，而 MVP 规模（千级物品）完全承受得住。
    """
    statement = select(Item, CurrentPrice).join(
        CurrentPrice, Item.item_id == CurrentPrice.item_id, isouter=True
    )
    # 只展示当前数据源的价格：换源（mock ↔ delta）后，另一套数据不该混进榜单。
    # 没有价格行的物品（外连接为 NULL）照常保留——它们是待采集目录。
    statement = statement.where(
        or_(
            CurrentPrice.item_id.is_(None),
            CurrentPrice.source == get_settings().data_source,
        )
    )
    if category:
        statement = statement.where(Item.primary_class == category)
    if sub_category:
        # 二级分类既可能是中文名（secondClassCN），也可能是代码（secondClass）。
        # 实测两种都可能出现，所以两个字段都匹配。
        statement = statement.where(
            or_(Item.second_class_cn == sub_category, Item.second_class == sub_category)
        )
    if search and search.strip():
        statement = statement.where(
            Item.name.like(f"%{_escape_like(search.strip())}%", escape="\\")
        )
    if grade is not None:
        statement = statement.where(Item.grade == grade)
    if tradable is not None:
        statement = statement.where(Item.is_tradable.is_(tradable))

    changes = load_price_changes(db)
    spread_stats = load_spread_stats(db)
    rows = [
        _to_out(item, price, changes.get(item.item_id), spread_stats.get(item.item_id))
        for item, price in db.execute(statement)
    ]
    _sort_rows(rows, sort, order)

    total = len(rows)
    return ItemListOut(
        items=rows[offset : offset + limit],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/items/{item_id}/history",
    response_model=ItemHistoryOut,
    summary="单物品历史价格",
)
def item_history(
    item_id: str,
    period: str = Query("24h", pattern="^(1h|24h|7d|30d)$", description="1h / 24h / 7d / 30d"),
    db: Session = Depends(get_db),
) -> ItemHistoryOut:
    """返回某个物品在指定时间窗内的价格快照序列。

    时间锚点是该物品**最新一条快照**，而不是服务器当前时间——即使采集停了几天，
    曲线依然能正确显示最后一段可用数据。不做过采样聚合：每天 3 次采集下
    30 天也只有 90 个点，原样返回即可。
    """
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"物品不存在: {item_id}")

    anchor: datetime | None = db.scalar(
        select(func.max(PriceHistory.recorded_at)).where(PriceHistory.item_id == item_id)
    )
    window_start = (anchor or utcnow()) - HISTORY_PERIODS[period]

    records = db.scalars(
        select(PriceHistory)
        .where(
            PriceHistory.item_id == item_id,
            PriceHistory.recorded_at >= window_start,
        )
        .order_by(PriceHistory.recorded_at)
    ).all()
    points = [PricePointOut(t=record.recorded_at, price=record.price) for record in records]

    return ItemHistoryOut(
        item_id=item.item_id,
        name=item.name,
        period=period,
        point_count=len(points),
        change_pct=change_pct(points[-1].price, points[0].price) if len(points) >= 2 else None,
        points=points,
    )


# --------------------------------------------------------------------------- #
# 内部辅助
# --------------------------------------------------------------------------- #
def _to_out(
    item: Item,
    price: CurrentPrice | None,
    change: PriceChange | None,
    stats: SpreadStats | None,
) -> ItemPriceOut:
    latest_price = None
    if price is not None:
        latest_price = price.price
    if latest_price is None and change is not None:
        # 没有 current_price 但有历史快照时，退回到快照里的最新价
        latest_price = change.price

    area = item.slot_area
    return ItemPriceOut(
        item_id=item.item_id,
        name=item.name,
        category=item.primary_class,
        # 正常取中文名；个别数据缺中文名时退回代码，避免只丢 null 给前端
        sub_category=item.second_class_cn or item.second_class,
        sub_category_code=item.second_class,
        grade=item.grade,
        pic_url=item.pic_url,
        is_tradable=item.is_tradable,
        slot_w=item.slot_w,
        slot_h=item.slot_h,
        slot_area=area,
        price_per_slot=(latest_price // area) if latest_price is not None and area else None,
        previous_price=change.previous_price if change else None,
        previous_price_at=change.previous_recorded_at if change else None,
        price=latest_price,
        price_start=price.price_start if price else None,
        price_delta=(
            abs(latest_price - price.price_start)
            if latest_price is not None
            and price is not None
            and price.price_start is not None
            else None
        ),
        restock_price=stats.restock_price if stats else None,
        restock_at=stats.restock_at if stats else None,
        high_24h=stats.high_24h if stats else None,
        high_24h_at=stats.high_24h_at if stats else None,
        spread_24h=stats.spread if stats else None,
        bl_today=price.bl_today if price else None,
        day_3_bl=price.day_3_bl if price else None,
        day_7_bl=price.day_7_bl if price else None,
        day_30_bl=price.day_30_bl if price else None,
        change_prev_pct=change.change_prev_pct if change else None,
        change_24h_pct=change.change_24h_pct if change else None,
        change_7d_pct=change.change_7d_pct if change else None,
        status=price.status if price else "unknown",
        is_stale=bool(price.is_stale) if price else False,
        source_updated_at=price.source_updated_at if price else None,
        updated_at=price.updated_at if price else None,
    )


def _sort_rows(rows: list[ItemPriceOut], field: SortField, order: SortOrder) -> None:
    """按字段排序，且**永远把空值排在最后**。

    直接 `reverse=True` 会把 null 排到最前面，所以先用中性值排一次，
    再用稳定排序把空值统一压到队尾。
    """
    is_text = field is SortField.name
    rows.sort(
        key=lambda row: _non_null(getattr(row, field.value), is_text),
        reverse=order is SortOrder.desc,
    )
    rows.sort(key=lambda row: getattr(row, field.value) is None)
    if field in CHANGE_SORT_FIELDS:
        # 稳定排序：最后执行的这一轮优先级最高，把收集品/钥匙卡整体挪到队尾，
        # 它们内部仍保持上面的涨幅顺序
        rows.sort(
            key=lambda row: (
                1
                if row.sub_category_code in DEPRIORITIZED_SUB_CATEGORIES
                or row.sub_category in DEPRIORITIZED_SUB_CATEGORIES
                else 0
            )
        )


def _non_null(value: float | str | None, is_text: bool) -> float | str:
    if value is None:
        return "" if is_text else 0
    return value


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符：用户输入 `%` 或 `_` 时不该把整表都匹配出来。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
