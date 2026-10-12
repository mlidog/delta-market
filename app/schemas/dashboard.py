"""看板摘要响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import UtcModel


class CollectRunOut(UtcModel):
    id: int
    source: str
    status: str
    items_ok: int
    items_failed: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class DashboardSummaryOut(UtcModel):
    item_count: int = Field(description="物品总数")
    tradable_count: int = Field(description="其中可在交易行交易的物品数")
    priced_count: int = Field(description="有价格数据的物品数")

    rising_count: int = Field(description="今日上涨数量（平台口径 bl_today > 0）")
    falling_count: int = Field(description="今日下跌数量（bl_today < 0）")
    flat_count: int = Field(description="今日持平数量（bl_today == 0）")
    stale_count: int = Field(description="本轮采集未刷新、保留旧价的物品数")

    data_source: str
    last_collect: CollectRunOut | None = None
    generated_at: datetime
