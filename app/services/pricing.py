"""涨跌幅计算。

三组口径都以**最近一次采集时间**为锚点，全部基于本地历史快照，不需要额外调用付费接口：

* `change_prev_pct`：与上一次采集相比（倒数第二条快照）
* `change_24h_pct`：与 24 小时前（或之前最近的一条快照）相比
* `change_7d_pct`：与 7 天前（或之前最近的一条快照）相比

历史不足时返回 `None` 而不是 0——"没有数据"和"没有变化"必须能区分开，
否则前端会把刚上线的物品显示成"价格零波动"。

与平台自带口径（`bl_today` / `day_3_bl` / `day_7_bl` / `day_30_bl`）的关系：
平台口径由数据源直接返回并存在 `current_price` 里，两套并存、互不替代。

另外提供 `load_day_stats()`：按**北京时间的"当天"**统计每个物品的补货价与最高价。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PriceHistory
from app.utils import utcnow

WINDOW_24H = timedelta(hours=24)
WINDOW_7D = timedelta(days=7)

#: 北京时间与 UTC 的固定偏移（中国没有夏令时，用固定值即可）
BEIJING_OFFSET = timedelta(hours=8)


@dataclass(frozen=True, slots=True)
class PriceChange:
    """某个物品的三组涨跌幅。"""

    price: int | None = None
    #: 上一次采集的价格（展示用；涨跌幅由它和 price 算出）
    previous_price: int | None = None
    #: 上一次采集的时间（展示用，说明那个价格是什么时候的）
    previous_recorded_at: datetime | None = None
    change_prev_pct: float | None = None
    change_24h_pct: float | None = None
    change_7d_pct: float | None = None


def change_pct(current: int | None, reference: int | None) -> float | None:
    """涨跌幅（百分比，保留两位小数）。"""
    if current is None or reference is None or reference == 0:
        return None
    return round((current - reference) / reference * 100, 2)


@dataclass(frozen=True, slots=True)
class DayStats:
    """某个物品"当天"（北京时间自然日）的补货价与最高价。

    补货价的口径：**当天 0 点后第一条快照的价格**。游戏每天 0 点补货，
    我们正好在 0 点采集一次，那条快照就是补货后的市场价。
    平台接口里没有"补货价"字段（`item_price_all` 只给 price / price_start /
    day_N_price），所以只能用我们自己的采样值，好在它就是直接测量。

    最高价同样来自当天的快照，因此精度受采样频率限制——每天 3 次采集时，
    "当天最高价"实际是 3 个采样点里的最高值。
    """

    restock_price: int | None = None
    restock_at: datetime | None = None
    day_high: int | None = None
    day_high_at: datetime | None = None

    @property
    def spread(self) -> int | None:
        """价差 = 当天最高价 − 补货价。结构上恒 ≥ 0（最高价里含补货那一条）。"""
        if self.day_high is None or self.restock_price is None:
            return None
        return self.day_high - self.restock_price


def beijing_day_start(now: datetime | None = None) -> datetime:
    """北京时间"今天 0 点"对应的 UTC 时刻（naive，与库里的时间口径一致）。"""
    beijing_now = (now or utcnow()) + BEIJING_OFFSET
    return datetime.combine(beijing_now.date(), time.min) - BEIJING_OFFSET


def load_day_stats(session: Session, now: datetime | None = None) -> dict[str, DayStats]:
    """一次算出全部物品当天的补货价、最高价与价差。

    用窗口函数一趟扫完：`rn_first` 取当天最早的一条（补货价），
    `rn_high` 取当天价格最高的一条（并列时取更早的那条，时间更有参考意义）。
    """
    day_start = beijing_day_start(now)
    ranked = (
        select(
            PriceHistory.item_id.label("item_id"),
            PriceHistory.price.label("price"),
            PriceHistory.recorded_at.label("recorded_at"),
            func.row_number()
            .over(
                partition_by=PriceHistory.item_id,
                order_by=PriceHistory.recorded_at,
            )
            .label("rn_first"),
            func.row_number()
            .over(
                partition_by=PriceHistory.item_id,
                order_by=(PriceHistory.price.desc(), PriceHistory.recorded_at),
            )
            .label("rn_high"),
        )
        .where(PriceHistory.recorded_at >= day_start)
        .subquery()
    )

    stats: dict[str, DayStats] = {}
    for item_id, price, recorded_at, rn_first, rn_high in session.execute(
        select(
            ranked.c.item_id,
            ranked.c.price,
            ranked.c.recorded_at,
            ranked.c.rn_first,
            ranked.c.rn_high,
        ).where((ranked.c.rn_first == 1) | (ranked.c.rn_high == 1))
    ):
        current = stats.get(item_id, DayStats())
        if rn_first == 1:
            current = DayStats(
                restock_price=price,
                restock_at=recorded_at,
                day_high=current.day_high,
                day_high_at=current.day_high_at,
            )
        if rn_high == 1:
            current = DayStats(
                restock_price=current.restock_price,
                restock_at=current.restock_at,
                day_high=price,
                day_high_at=recorded_at,
            )
        stats[item_id] = current
    return stats


def load_price_changes(session: Session) -> dict[str, PriceChange]:
    """一次算出全部物品的三组涨跌幅。

    实现说明：故意不按"当前页的物品 ID"过滤，因为 SQLite 对单条 SQL 的绑定变量数量
    有上限（老版本仅 999），而全量物品有 1200+ 个。全量计算再在内存里筛，反而更稳。
    """
    latest, previous = _latest_and_previous(session)
    if not latest:
        return {}

    anchor = max(stamp for stamp, _ in latest.values())
    ref_24h = _prices_before(session, anchor - WINDOW_24H)
    ref_7d = _prices_before(session, anchor - WINDOW_7D)

    changes: dict[str, PriceChange] = {}
    for item_id, (latest_at, price) in latest.items():
        changes[item_id] = PriceChange(
            price=price,
            previous_price=previous[item_id][1] if item_id in previous else None,
            previous_recorded_at=previous[item_id][0] if item_id in previous else None,
            change_prev_pct=change_pct(
                price, previous[item_id][1] if item_id in previous else None
            ),
            # 参考点必须真的早于该物品自己的最新快照，否则说明这物品已经很久没数据了
            change_24h_pct=_reference_change(price, latest_at, ref_24h.get(item_id)),
            change_7d_pct=_reference_change(price, latest_at, ref_7d.get(item_id)),
        )
    return changes


def _reference_change(
    price: int | None, latest_at: datetime, reference: tuple[datetime, int] | None
) -> float | None:
    if reference is None:
        return None
    reference_at, reference_price = reference
    if reference_at >= latest_at:
        return None
    return change_pct(price, reference_price)


def _latest_and_previous(
    session: Session,
) -> tuple[dict[str, tuple[datetime, int]], dict[str, tuple[datetime, int]]]:
    """用窗口函数一次取出每个物品的最新价与上一次采集价。"""
    ranked = (
        select(
            PriceHistory.item_id.label("item_id"),
            PriceHistory.price.label("price"),
            PriceHistory.recorded_at.label("recorded_at"),
            func.row_number()
            .over(
                partition_by=PriceHistory.item_id,
                order_by=PriceHistory.recorded_at.desc(),
            )
            .label("rank"),
        )
        .subquery()
    )

    latest: dict[str, tuple[datetime, int]] = {}
    previous: dict[str, tuple[datetime, int]] = {}
    for item_id, price, recorded_at, rank in session.execute(
        select(ranked.c.item_id, ranked.c.price, ranked.c.recorded_at, ranked.c.rank).where(
            ranked.c.rank <= 2
        )
    ):
        if rank == 1:
            latest[item_id] = (recorded_at, price)
        else:
            previous[item_id] = (recorded_at, price)
    return latest, previous


def _prices_before(session: Session, target: datetime) -> dict[str, tuple[datetime, int]]:
    """每个物品在 `target` 时刻或之前最近的一条快照。"""
    newest = (
        select(
            PriceHistory.item_id.label("item_id"),
            func.max(PriceHistory.recorded_at).label("recorded_at"),
        )
        .where(PriceHistory.recorded_at <= target)
        .group_by(PriceHistory.item_id)
        .subquery()
    )
    rows = session.execute(
        select(PriceHistory.item_id, PriceHistory.recorded_at, PriceHistory.price).join(
            newest,
            (PriceHistory.item_id == newest.c.item_id)
            & (PriceHistory.recorded_at == newest.c.recorded_at),
        )
    )
    return {item_id: (recorded_at, price) for item_id, recorded_at, price in rows}
