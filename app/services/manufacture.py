"""特勤处制造收益同步。

与价格采集的差别：

* 接口返回的是**当前时点的完整榜单**，所以每次同步按（站点 + 等级 + 来源）整段替换，
  不做历史累积；
* 单个站点失败不影响其他站点（每个站点的数据是独立的），失败信息收进 `errors`；
* 一次完整同步 = 4 站点 × 3 等级 = 12 次请求 = 12 次资源（数据帝 manufacturePro 计费）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.data_sources import (
    STATION_IDS,
    STATION_KEYS,
    DataSource,
    DataSourceError,
    ManufactureRecord,
)
from app.models import ManufactureProfit
from app.utils import utcnow

#: 部门等级 1 / 2 / 3 —— 等级不同，生产时长与收益都不同，必须分开取
DEFAULT_LEVELS: tuple[int, ...] = (1, 2, 3)


@dataclass(slots=True)
class ManufactureSyncResult:
    rows: int = 0
    requests: int = 0
    station_levels: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def sync_manufacture(
    session: Session,
    source: DataSource,
    *,
    stations: Iterable[str] | None = None,
    levels: Iterable[int] = DEFAULT_LEVELS,
    clock: Callable[[], datetime] = utcnow,
) -> ManufactureSyncResult:
    """把特勤处制造收益拉下来并整段替换进库。"""
    result = ManufactureSyncResult(started_at=clock())
    station_keys = list(stations) if stations is not None else list(STATION_KEYS.values())

    for station in station_keys:
        station_id = STATION_IDS.get(station)
        if station_id is None:
            result.errors.append(f"未知站点：{station}")
            continue
        for level in levels:
            result.requests += 1
            try:
                records = source.fetch_manufacture(station_id, level)
            except DataSourceError as exc:
                result.errors.append(f"{station} L{level}：{exc}")
                continue
            result.rows += _replace(session, records, station, level, source.name, clock())
            result.station_levels += 1

    session.commit()
    result.finished_at = clock()
    return result


def _replace(
    session: Session,
    records: list[ManufactureRecord],
    station: str,
    level: int,
    source_name: str,
    moment: datetime,
) -> int:
    """整段替换某个（站点 + 等级）的榜单。

    删除条件是（站点 + 等级 + 口径）而**不带 source**：这张表存的是"当前榜单"，
    换数据源（mock ↔ delta）时旧数据必须被清掉，否则两套数据会在排行里并列。
    """
    origin = records[0].origin if records else "pro"
    session.execute(
        delete(ManufactureProfit).where(
            ManufactureProfit.station == station,
            ManufactureProfit.unlock_level == level,
            ManufactureProfit.origin == origin,
        )
    )
    for record in records:
        session.add(
            ManufactureProfit(
                station=record.station,
                unlock_level=record.unlock_level,
                item_key=record.item_key,
                name=record.name,
                origin=record.origin,
                period_hours=record.period_hours,
                market_price=record.market_price,
                fee=record.fee,
                profit=record.profit,
                profit_per_hour=record.profit_per_hour,
                grade=record.grade,
                primary_class=record.primary_class,
                second_class_cn=record.second_class_cn,
                pic_url=record.pic_url,
                is_get=record.is_get,
                is_pay=record.is_pay,
                source=source_name,
                fetched_at=moment,
                raw_json=(
                    json.dumps(record.raw, ensure_ascii=False, sort_keys=True)
                    if record.raw
                    else None
                ),
            )
        )
    session.flush()
    return len(records)
