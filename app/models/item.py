"""物品主数据。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Item(Base):
    """交易行物品。

    主键使用「三角洲数据帝」的第三代数据 ID（`oid`），它同时也是价格接口
    `item_price_all` 返回的 `id`，两边可以一一对应。
    """

    __tablename__ = "items"

    item_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # 分类：一级（ammo/acc/gun/...）、二级代码、二级中文名
    primary_class: Mapped[str | None] = mapped_column(String(32), index=True)
    second_class: Mapped[str | None] = mapped_column(String(64))
    second_class_cn: Mapped[str | None] = mapped_column(String(64), index=True)

    grade: Mapped[int | None] = mapped_column(Integer, index=True)
    pic_url: Mapped[str | None] = mapped_column(String(255))
    is_tradable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    #: 三角洲官方小程序 ID，仅用于与官方数据对照
    object_id: Mapped[str | None] = mapped_column(String(32))

    #: 占格宽高，用于计算单格价值（price / (slot_w * slot_h)）
    slot_w: Mapped[int | None] = mapped_column(Integer)
    slot_h: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    @property
    def slot_area(self) -> int | None:
        """占格格数；宽高缺失时返回 None。"""
        if self.slot_w is None or self.slot_h is None:
            return None
        return self.slot_w * self.slot_h

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试
        return f"<Item {self.item_id} {self.name}>"
