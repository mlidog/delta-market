"""本地模拟数据源。

作用有两个：

1. 在拿到真实 Token 之前，让整条链路（采集 → 落库 → 接口 → 前端）都能开发与测试；
2. 为采集与重试逻辑提供可控的失败注入点。

模拟价格不是随机数，而是由 `(seed, 物品 ID, 时间)` 唯一决定的平滑波动函数，
因此同一时刻重复调用结果完全一致，跨时刻又有真实的价格涨落。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.data_sources.base import (
    DataSource,
    DataSourceUnavailableError,
    ItemRecord,
    PriceRecord,
)
from app.utils import utcnow

#: 默认随机种子
DEFAULT_SEED = 20261012


@dataclass(frozen=True, slots=True)
class _MockItem:
    external_id: str
    name: str
    primary_class: str
    second_class: str
    second_class_cn: str
    grade: int
    base_price: int
    slot_w: int
    slot_h: int
    is_tradable: bool = True
    object_id: str | None = None


#: 覆盖枪械 / 配件 / 子弹 / 防具 / 收集品 / 消耗品 / 钥匙卡，并特意包含：
#: - 两个不可交易物品（价格接口不应返回它们）
#: - 一个带磨损度后缀的名称（真实数据里同名物品会带 "(几乎全新)" 等后缀）
MOCK_CATALOG: tuple[_MockItem, ...] = (
    _MockItem("900001", "M4A1突击步枪", "gun", "gunRifle", "突击步枪", 4, 128_000, 2, 4),
    _MockItem("900002", "AKM突击步枪", "gun", "gunRifle", "突击步枪", 3, 76_000, 2, 4),
    _MockItem("900003", "ASh-12扩容30发弹匣", "acc", "accMag", "弹匣", 4, 62_473, 1, 2),
    _MockItem("900004", "Cobra准直式瞄准镜", "acc", "accScope", "瞄具", 3, 25_673, 1, 1),
    _MockItem("900005", "勇士战术枪管", "acc", "accBarrel", "枪管", 3, 42_035, 1, 2),
    _MockItem("900006", "6.8x51mm AP", "ammo", "ammo68", "ammo6.8x51", 6, 4_200, 1, 1),
    _MockItem("900007", "7.62x51mm M61", "ammo", "ammo762", "ammo7.62x51", 6, 3_800, 1, 1),
    _MockItem("900008", "5.56x45mm M855A1", "ammo", "ammo556", "ammo5.56x45", 5, 2_600, 1, 1),
    _MockItem("900009", "强袭战术背心", "protect", "chest", "胸挂", 4, 20_640, 2, 2),
    _MockItem("900010", "老式钢盔", "protect", "helmet", "头盔", 2, 1_324, 2, 2),
    _MockItem("900011", "6级复合护甲", "protect", "armor", "护甲", 6, 88_000, 2, 3),
    _MockItem("900012", "强袭背包", "protect", "bag", "背包", 4, 31_000, 3, 4),
    _MockItem("900013", "非洲之心", "collection", "collection", "收集品", 6, 13_141_314, 1, 1),
    _MockItem("900014", "海洋之泪", "collection", "collection", "收集品", 6, 31_011_123, 1, 1),
    _MockItem("900015", "聚乙烯纤维", "collection", "collection", "收集品", 3, 26_367, 2, 2),
    _MockItem("900016", "笔记本电脑", "collection", "collection", "收集品", 6, 632_110, 2, 3),
    _MockItem("900017", "复苏呼吸机", "collection", "collection", "收集品", 6, 441_098, 3, 3),
    _MockItem("900018", "扑克牌-大王", "collection", "collection", "收集品", 4, 13_000, 1, 1),
    _MockItem("900019", "止血带", "consume", "consume", "消耗品", 2, 1_800, 1, 1),
    _MockItem("900020", "能量饮料", "consume", "consume", "消耗品", 2, 950, 1, 1),
    _MockItem("900021", "零号大坝-西楼", "key", "key", "钥匙卡", 4, 168_000, 1, 1),
    _MockItem("900022", "航天基地-控制室", "key", "key", "钥匙卡", 5, 232_000, 1, 1),
    _MockItem("900023", "坦克模型（收藏）", "collection", "collection", "收集品", 5, 54_000, 2, 2, False),
    _MockItem("900024", "特勤处-机密文件", "collection", "collection", "收集品", 5, 12_000, 1, 1, False),
    _MockItem("900025", "老式钢盔 (几乎全新)", "protect", "helmet", "头盔", 3, 2_180, 2, 2),
)


class MockDataSource(DataSource):
    """返回模拟物品与价格的数据源。

    Args:
        seed: 波动函数的随机种子，相同种子 + 相同时刻得到相同结果。
        clock: 取"当前时间"的函数，测试时可注入固定时间。
        fail_first_n_calls: 前 N 次 `fetch_prices()` 抛可重试错误，
            用于验证 M3 的重试与失败标记逻辑。
    """

    name = "mock"

    def __init__(
        self,
        *,
        seed: int = DEFAULT_SEED,
        clock: Callable[[], datetime] = utcnow,
        fail_first_n_calls: int = 0,
    ) -> None:
        self._seed = seed
        self._clock = clock
        self._fail_remaining = max(0, fail_first_n_calls)
        self._price_calls = 0

    # ------------------------------------------------------------------ #
    # 数据源接口
    # ------------------------------------------------------------------ #
    def fetch_items(self) -> list[ItemRecord]:
        return [
            ItemRecord(
                external_id=item.external_id,
                name=item.name,
                primary_class=item.primary_class,
                second_class=item.second_class,
                second_class_cn=item.second_class_cn,
                grade=item.grade,
                pic_url=f"https://example.invalid/mock/{item.external_id}.png",
                is_tradable=item.is_tradable,
                object_id=item.object_id,
                slot_w=item.slot_w,
                slot_h=item.slot_h,
            )
            for item in MOCK_CATALOG
        ]

    def fetch_prices(self) -> list[PriceRecord]:
        self._price_calls += 1
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise DataSourceUnavailableError(
                f"模拟数据源故障（第 {self._price_calls} 次调用）"
            )

        moment = self._clock()
        # 不可交易物品在真实接口里没有价格，这里保持一致
        return [
            self._build_price(item, moment)
            for item in MOCK_CATALOG
            if item.is_tradable
        ]

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _build_price(self, item: _MockItem, moment: datetime) -> PriceRecord:
        price = self._price_at(item, moment)
        price_start = self._price_at(item, moment.replace(hour=0, minute=0, second=0, microsecond=0))
        day_3 = self._price_at(item, moment - timedelta(days=3))
        day_7 = self._price_at(item, moment - timedelta(days=7))
        day_30 = self._price_at(item, moment - timedelta(days=30))

        record = PriceRecord(
            external_id=item.external_id,
            price=price,
            price_start=price_start,
            bl_today=_change_pct(price, price_start),
            day_3_price=day_3,
            day_3_bl=_change_pct(price, day_3),
            day_7_price=day_7,
            day_7_bl=_change_pct(price, day_7),
            day_30_price=day_30,
            day_30_bl=_change_pct(price, day_30),
            source_updated_at=moment.replace(minute=0, second=0, microsecond=0),
        )
        # 原始记录按数据帝的字段名组织，保证 raw_json 的读写路径与真实源一致
        return PriceRecord(
            **{
                **{f: getattr(record, f) for f in record.__slots__ if f != "raw"},
                "raw": {
                    "id": _as_int(item.external_id),
                    "price": record.price,
                    "price_start": record.price_start,
                    "bl": record.bl_today,
                    "day_3_price": record.day_3_price,
                    "day_3_bl": record.day_3_bl,
                    "day_7_price": record.day_7_price,
                    "day_7_bl": record.day_7_bl,
                    "day_30_price": record.day_30_price,
                    "day_30_bl": record.day_30_bl,
                    "is_get_time": int(record.source_updated_at.timestamp())
                    if record.source_updated_at
                    else None,
                },
            }
        )

    def _price_at(self, item: _MockItem, moment: datetime) -> int:
        """由 (seed, 物品, 时刻) 决定的平滑价格波动。"""
        digest = hashlib.sha256(f"{self._seed}:{item.external_id}".encode()).digest()
        phase = int.from_bytes(digest[:4], "big") / 2**32 * math.tau
        amplitude = 0.05 + int.from_bytes(digest[4:6], "big") / 2**16 * 0.10

        hours = moment.timestamp() / 3600.0
        wave = (
            math.sin(hours / 11.0 + phase) * amplitude
            + math.sin(hours / 3.7 + phase * 2) * amplitude * 0.35
            + math.sin(hours / 97.0 + phase / 3) * amplitude * 1.5
        )
        return max(1, round(item.base_price * (1.0 + wave)))


def _change_pct(current: int, reference: int) -> float | None:
    """涨跌幅（百分比），保留两位小数；参考价非法时返回 None。"""
    if not reference:
        return None
    return round((current - reference) / reference * 100, 2)


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
