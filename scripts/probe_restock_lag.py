"""测量"0 点补货"在数据帝接口上的延迟（**会消耗资源，请按需运行**）。

背景：游戏每天 0 点补货，但接口上的价格不是立刻变的。2026-10-15 实测 10 个品种：
0:02 拿到的往往还是补货前的高价，补货形成的低点出现在 00:07~00:30，快的品种
5~15 分钟内就回弹。所以 0 点这一档往后挪了 15 分钟（`COLLECTOR_CRON_MINUTE`）。

本脚本用 `minute` 接口（每个物品 1 次资源）拉最近 24 小时的分钟级曲线，
打印凌晨那段的价格走势并统计低点出现时刻，用来复核上面这个结论。

用法（必须从项目根目录用 `-m` 运行）：:

    .\\.venv\\Scripts\\python.exe -m scripts.probe_restock_lag
    .\\.venv\\Scripts\\python.exe -m scripts.probe_restock_lag --items "AWM狙击步枪" --limit 1
"""

from __future__ import annotations

import argparse
import re
import statistics

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Item
from app.data_sources.delta import USER_AGENT

#: 默认探测的品种：成交活跃、价格量级不同，能代表不同回弹速度
DEFAULT_ITEMS = [
    "H70 精英头盔",
    "微型反应炉",
    "AWM狙击步枪",
    "7.62x51mm LS",
    "曼德尔超算单元",
    "重型登山包",
    "GN 重型夜视头盔",
    "碳纤维刺骨箭矢",
    "DT-AVS防弹衣",
    "M4A1突击步枪",
]

#: 凌晨窗口（只看这几个小时内的低点）
NIGHT_HOURS = 3


def parse_label(label: str) -> tuple[int, int, int] | None:
    """把 `10-15 13:37分` 解析成 (日, 时, 分)，避开中文编码问题。"""
    match = re.search(r"(\d{2})-(\d{2})\D+(\d{2}):(\d{2})", label)
    if match is None:
        return None
    return int(match.group(2)), int(match.group(3)), int(match.group(4))


def fetch_series(client: httpx.Client, item_id: str) -> list[tuple[tuple[int, int, int], int]]:
    settings = get_settings()
    response = client.get(
        f"{settings.delta_api_base_url}/v1/sjz_api/minute",
        params={"id": item_id, "token": settings.delta_api_token_value},
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    points = [
        (parse_label(label), price)
        for label, price in zip(data.get("a") or [], data.get("b") or [])
    ]
    return sorted([(t, p) for t, p in points if t is not None], key=lambda x: x[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="测量补货价在接口上的延迟")
    parser.add_argument("--items", nargs="*", default=DEFAULT_ITEMS, help="物品名称")
    parser.add_argument("--limit", type=int, default=0, help="最多探测几个（0 表示不限）")
    args = parser.parse_args()

    names = args.items[: args.limit] if args.limit else args.items
    session = SessionLocal()
    targets = []
    for name in names:
        row = session.scalars(select(Item).where(Item.name == name)).first()
        if row is None:
            print(f"跳过（库里没有这个物品）：{name}")
            continue
        targets.append((row.item_id, name))
    session.close()

    print(f"探测 {len(targets)} 个物品，将消耗 {len(targets)} 次资源")
    delays: list[int] = []
    with httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
        for item_id, name in targets:
            points = fetch_series(client, item_id)
            if not points:
                print(f"  {name}: 没有数据")
                continue
            night = [x for x in points if x[0][1] < NIGHT_HOURS]
            low_time, low_price = min(night, key=lambda x: x[1]) if night else ((0, 0, 0), 0)
            first = min(night, key=lambda x: (x[0][1], x[0][2])) if night else None
            delay = low_time[1] * 60 + low_time[2]
            delays.append(delay)
            print(
                f"  {name:<14} 凌晨低点 {low_price:>9} @{low_time[1]:02d}:{low_time[2]:02d}"
                + (f"（0 点首个采样 {first[1]:>9}）" if first else "")
                + f"  → 延迟 {delay} 分钟"
            )

    if delays:
        delays.sort()
        print(f"\n低点延迟（分钟，0 点起算）：{delays}")
        print(f"中位数 {statistics.median(delays)} 分钟")


if __name__ == "__main__":
    main()
