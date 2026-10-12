"""当前价格与历史价格快照。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils import utcnow


class PriceStatus(str, Enum):
    """当前价数据的可用状态。"""

    OK = "ok"
    """本次采集成功，价格是新鲜的。"""

    STALE = "stale"
    """最近一次采集失败，展示的是上一次成功采集的价格。"""


class CurrentPrice(Base):
    """每个物品一行的当前价格快照（列表页只查这一张表）。

    这是对 `price_history` 的有意反范式：既避免列表页做聚合查询，
    也用于承载采集失败、数据新鲜度等只属于"当前状态"的字段。
    """

    __tablename__ = "current_price"

    item_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("items.item_id", ondelete="CASCADE"),
        primary_key=True,
    )

    # --- 价格本体 ---
    price: Mapped[int | None] = mapped_column(Integer, index=True)
    price_start: Mapped[int | None] = mapped_column(Integer)

    # --- 平台算好的涨跌幅（随 item_price_all 免费返回）---
    bl_today: Mapped[float | None] = mapped_column(Float)
    day_3_price: Mapped[int | None] = mapped_column(Integer)
    day_3_bl: Mapped[float | None] = mapped_column(Float)
    day_7_price: Mapped[int | None] = mapped_column(Integer)
    day_7_bl: Mapped[float | None] = mapped_column(Float)
    day_30_price: Mapped[int | None] = mapped_column(Integer)
    day_30_bl: Mapped[float | None] = mapped_column(Float)

    # --- 数据来源与新鲜度 ---
    #: 平台给出的价格更新时间（对应接口的 is_get_time），UTC naive
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: 接口原始记录，便于平台新增字段时无需改表
    raw_json: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")

    # --- 采集状态 ---
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PriceStatus.OK.value
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    @property
    def is_stale(self) -> bool:
        return self.status == PriceStatus.STALE.value

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试
        return f"<CurrentPrice {self.item_id} {self.price} {self.status}>"


class PriceHistory(Base):
    """追加式价格快照，用于历史曲线与涨跌幅计算。"""

    __tablename__ = "price_history"
    __table_args__ = (
        # 同一物品同一时刻只允许一条，重复采集幂等
        UniqueConstraint("item_id", "recorded_at", name="uq_price_history_item_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("items.item_id", ondelete="CASCADE"),
        nullable=False,
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")
    # 不单独建索引：查询永远是"某物品 + 时间范围"，由下面的联合唯一约束覆盖
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试
        return f"<PriceHistory {self.item_id} {self.price} @{self.recorded_at}>"
