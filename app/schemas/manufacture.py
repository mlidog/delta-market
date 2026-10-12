"""特勤处制造收益的响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import UtcDateTime, UtcModel


class ManufactureItemOut(UtcModel):
    item_key: str
    name: str
    station: str = Field(description="站点标识：tech / workbench / pharmacy / armor")
    station_label: str = Field(description="站点中文名")
    unlock_level: int = Field(description="部门等级 1~3；官方口径为 0")

    grade: int | None = None
    category: str | None = None
    sub_category: str | None = None
    pic_url: str | None = None

    period_hours: float | None = Field(None, description="制造时长（小时）")
    market_price: int | None = Field(None, description="未扣手续费的参考价")
    fee: int | None = Field(None, description="手续费 + 上架费")
    profit: int | None = Field(None, description="净收益（已扣除材料成本与手续费）")
    profit_per_hour: int | None = Field(None, description="每小时净收益")

    origin: str = Field("pro", description="pro=自有源计算，official=官方数据")
    fetched_at: UtcDateTime | None = None


class ManufactureStationOut(BaseModel):
    key: str
    label: str
    station_id: int


class ManufactureListOut(UtcModel):
    items: list[ManufactureItemOut]
    total: int
    limit: int
    offset: int
    stations: list[ManufactureStationOut]
    levels: list[int]
    origin: str
    source: str = Field(description="榜单数据来源（mock / delta）")
    fetched_at: UtcDateTime | None = Field(None, description="本榜数据的抓取时间")


class ManufactureStationGroupOut(BaseModel):
    """一个站点的排行分组。"""

    station: str
    label: str
    station_id: int
    total: int = Field(description="该站点符合筛选条件的条目总数")
    items: list[ManufactureItemOut]


class ManufactureGroupedOut(UtcModel):
    """按站点分组的制造收益排行。"""

    groups: list[ManufactureStationGroupOut]
    levels: list[int]
    origin: str
    source: str
    sort: str
    order: str
    per_station: int = Field(description="每个站点返回的条目上限")
    fetched_at: UtcDateTime | None = None


class ManufactureSyncOut(UtcModel):
    rows: int = Field(description="写入的记录数")
    requests: int = Field(description="发起的接口请求数（每次消耗 1 次资源）")
    station_levels: int = Field(description="成功的站点×等级组合数")
    errors: list[str] = Field(default_factory=list)
    started_at: UtcDateTime | None = None
    finished_at: UtcDateTime | None = None
