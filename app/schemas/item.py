"""物品与价格的响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import UtcModel


class ItemPriceOut(UtcModel):
    """列表里的一个物品：基础信息 + 当前价 + 六组涨跌幅。"""

    item_id: str
    name: str
    category: str | None = Field(None, description="一级分类，如 ammo / acc / gun")
    sub_category: str | None = Field(None, description="二级分类中文名，如 瞄具 / 胸挂")
    grade: int | None = None
    pic_url: str | None = None
    is_tradable: bool = True

    # --- 占格与单格价值 ---
    slot_w: int | None = None
    slot_h: int | None = None
    slot_area: int | None = Field(None, description="占格格数 = slot_w × slot_h")
    price_per_slot: int | None = Field(None, description="单格价值 = price ÷ slot_area")

    # --- 价格 ---
    price: int | None = None
    price_start: int | None = Field(None, description="平台口径的今日最初价格")

    # --- 平台口径涨跌幅（随全量价格接口免费返回）---
    bl_today: float | None = None
    day_3_bl: float | None = None
    day_7_bl: float | None = None
    day_30_bl: float | None = None

    # --- 本地口径涨跌幅（基于我们自己积累的快照，历史不足为 null）---
    change_prev_pct: float | None = Field(None, description="与上一次采集相比")
    change_24h_pct: float | None = Field(None, description="与 24 小时前相比")
    change_7d_pct: float | None = Field(None, description="与 7 天前相比")

    # --- 数据状态 ---
    status: str = Field("ok", description="ok 表示本轮采集成功，stale 表示保留的是旧价")
    is_stale: bool = False
    source_updated_at: datetime | None = None
    updated_at: datetime | None = None


class ItemListOut(BaseModel):
    items: list[ItemPriceOut]
    total: int = Field(description="符合筛选条件的物品总数（未经分页）")
    limit: int
    offset: int


class PricePointOut(UtcModel):
    t: datetime
    price: int


class ItemHistoryOut(UtcModel):
    item_id: str
    name: str
    period: str
    point_count: int
    change_pct: float | None = Field(
        None, description="区间首尾价格变化百分比，点数不足时为 null"
    )
    points: list[PricePointOut]
