"""特勤处制造收益。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils import utcnow


class ManufactureProfit(Base):
    """一条「站点 + 部门等级 + 产出物品」的制造收益记录。

    与价格快照不同，这里**不做历史累积**：接口返回的是"当前时点的完整榜单"，
    每次同步按（站点 + 等级 + 数据来源）整段替换。制造收益随时会变，
    留着一堆过期榜单只会误导排序。

    字段口径（已用官方接口交叉验证）：

    * `profit`：已扣除材料成本与手续费的净收益（接口字段 `price`）
    * `profit_per_hour`：每小时净收益（接口字段 `price_hour`）
    * `market_price`：未扣手续费的参考价（接口字段 `priceMax`）
    * `fee`：手续费 + 上架费（接口字段 `sxf`）
    """

    __tablename__ = "manufacture_profit"
    __table_args__ = (
        UniqueConstraint(
            "station",
            "unlock_level",
            "item_key",
            "origin",
            name="uq_manufacture_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: 站点机器标识：tech / workbench / pharmacy / armor
    station: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: 部门等级 1~3；官方口径不区分等级，记为 0
    unlock_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: 产出物品标识（数据帝返回的官方 objectID）
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    #: pro（自有源计算）/ official（官方数据，官方自述"不准"）
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="pro")

    period_hours: Mapped[float | None] = mapped_column(Float)
    market_price: Mapped[int | None] = mapped_column(Integer)
    fee: Mapped[int | None] = mapped_column(Integer)
    profit: Mapped[int | None] = mapped_column(Integer, index=True)
    profit_per_hour: Mapped[int | None] = mapped_column(Integer, index=True)

    grade: Mapped[int | None] = mapped_column(Integer)
    primary_class: Mapped[str | None] = mapped_column(String(32))
    second_class_cn: Mapped[str | None] = mapped_column(String(64))
    pic_url: Mapped[str | None] = mapped_column(String(255))
    is_get: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    is_pay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    source: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    raw_json: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试
        return f"<ManufactureProfit {self.station} L{self.unlock_level} {self.name} {self.profit}>"
