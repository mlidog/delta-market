"""导出静态数据，供 GitHub Pages 版本使用。

设计要点：**数据库是可丢弃的缓存，JSON 才是持久状态**。
云端（GitHub Actions）每次都是全新环境，没有本地那份 SQLite，
所以流程是：

1. 用上一次导出的 `items.json` 预热物品目录（否则每轮都要花 20 次资源重拉目录）
2. 用 `history.json` 回填 `price_history`，这样涨跌幅计算能**完全复用**本地那套逻辑
3. 采集一次价格、同步一次制造收益
4. 写出 `frontend/public/data/*.json`

这些 JSON 会被工作流提交回仓库，于是"上一次的状态"就有了着落。

用法：

    python -m scripts.export_static              # 完整流程（会消耗平台资源）
    python -m scripts.export_static --no-collect # 只用现有数据库重新导出（不联网、不花钱）
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.config import BASE_DIR, get_settings
from app.data_sources import STATION_IDS, STATION_NAMES, create_data_source
from app.database import SessionLocal, init_db
from app.models import CollectRun, CurrentPrice, Item, ManufactureProfit, PriceHistory, PriceStatus
from app.services import Collector
from app.services.manufacture import sync_manufacture
from app.services.pricing import load_price_changes
from app.utils import utcnow

DATA_DIR = BASE_DIR / "frontend" / "public" / "data"

#: 静态版保留多少天的历史快照（用于曲线与"较 7 天前"）
HISTORY_DAYS = 30


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text)


def seed_from_previous_export(session: Session) -> tuple[int, int]:
    """把上一次导出的目录与历史灌回数据库，让云端运行也能"有记忆"。"""
    if session.scalar(select(func.count()).select_from(Item)):
        # 本地数据库本来就是完整的，不需要预热；云端每次都是空库，才会走到下面
        return 0, 0

    items = _read_json(DATA_DIR / "items.json", [])
    history = _read_json(DATA_DIR / "history.json", {})
    meta = _read_json(DATA_DIR / "meta.json", {})
    catalog_time = _parse_iso(meta.get("generated_at")) or utcnow()

    for row in items:
        session.add(
            Item(
                item_id=row["item_id"],
                name=row["name"],
                primary_class=row.get("category"),
                second_class=row.get("sub_category_code"),
                second_class_cn=row.get("sub_category"),
                grade=row.get("grade"),
                pic_url=row.get("pic_url"),
                is_tradable=row.get("is_tradable", True),
                slot_w=row.get("slot_w"),
                slot_h=row.get("slot_h"),
                # 目录时间沿用上次导出的时间，7 天缓存策略才能正常生效
                created_at=catalog_time,
                updated_at=catalog_time,
            )
        )
        if row.get("price") is not None:
            session.add(
                CurrentPrice(
                    item_id=row["item_id"],
                    price=row["price"],
                    price_start=row.get("price_start"),
                    bl_today=row.get("bl_today"),
                    day_3_bl=row.get("day_3_bl"),
                    day_7_bl=row.get("day_7_bl"),
                    day_30_bl=row.get("day_30_bl"),
                    source=get_settings().data_source,
                    status=PriceStatus.OK.value,
                    updated_at=catalog_time,
                )
            )

    snapshots = 0
    for item_id, points in history.items():
        for stamp, price in points:
            session.add(
                PriceHistory(
                    item_id=item_id,
                    price=price,
                    source=get_settings().data_source,
                    recorded_at=datetime.fromtimestamp(int(stamp)).replace(microsecond=0),
                )
            )
            snapshots += 1

    session.commit()
    return len(items), snapshots


def collect(session: Session) -> str | None:
    """采集价格并同步制造收益，返回错误信息（成功返回 None）。"""
    collector = Collector()
    result = collector.run()
    print(f"  采集：{result.status.value} 价格 {result.prices_written} 条 快照 {result.history_written} 条")
    if result.error:
        print(f"  采集错误：{result.error}")

    source = create_data_source()
    try:
        sync = sync_manufacture(session, source)
        print(f"  制造：写入 {sync.rows} 条，请求 {sync.requests} 次")
        if sync.errors:
            print("  制造错误：" + "；".join(sync.errors))
    finally:
        source.close()
    return result.error


def export(session: Session) -> dict[str, int]:
    """把数据库内容导出成前端可直接读取的 JSON。"""
    settings = get_settings()
    active_source = settings.data_source
    changes = load_price_changes(session)

    items: list[dict[str, Any]] = []
    rows = session.execute(select(Item, CurrentPrice).join(
        CurrentPrice, Item.item_id == CurrentPrice.item_id, isouter=True
    ).where(CurrentPrice.source == active_source)).all()
    for item_row, price_row in rows:
        change = changes.get(item_row.item_id)
        area = item_row.slot_area
        latest = price_row.price if price_row else (change.price if change else None)
        items.append(
            {
                "item_id": item_row.item_id,
                "name": item_row.name,
                "category": item_row.primary_class,
                "sub_category": item_row.second_class_cn or item_row.second_class,
                "sub_category_code": item_row.second_class,
                "grade": item_row.grade,
                "pic_url": item_row.pic_url,
                "is_tradable": item_row.is_tradable,
                "slot_w": item_row.slot_w,
                "slot_h": item_row.slot_h,
                "slot_area": area,
                "price_per_slot": (latest // area) if latest is not None and area else None,
                "price": latest,
                "price_start": price_row.price_start if price_row else None,
                "bl_today": price_row.bl_today if price_row else None,
                "day_3_bl": price_row.day_3_bl if price_row else None,
                "day_7_bl": price_row.day_7_bl if price_row else None,
                "day_30_bl": price_row.day_30_bl if price_row else None,
                "change_prev_pct": change.change_prev_pct if change else None,
                "change_24h_pct": change.change_24h_pct if change else None,
                "change_7d_pct": change.change_7d_pct if change else None,
                "status": price_row.status if price_row else "unknown",
                "is_stale": bool(price_row.is_stale) if price_row else False,
                "source_updated_at": _iso(price_row.source_updated_at) if price_row else None,
                "updated_at": _iso(price_row.updated_at) if price_row else None,
            }
        )
    items.sort(key=lambda row: row["item_id"])

    # 历史：只保留最近 HISTORY_DAYS 天，按物品聚合、时间升序
    since = utcnow() - timedelta(days=HISTORY_DAYS)
    history: dict[str, list[list[int]]] = defaultdict(list)
    for item_id, recorded_at, price in session.execute(
        select(PriceHistory.item_id, PriceHistory.recorded_at, PriceHistory.price)
        .where(PriceHistory.recorded_at >= since, PriceHistory.source == active_source)
        .order_by(PriceHistory.recorded_at)
    ):
        history[item_id].append([int(recorded_at.timestamp()), price])

    manufacture = [
        {
            "item_key": row.item_key,
            "name": row.name,
            "station": row.station,
            "station_label": STATION_NAMES.get(STATION_IDS.get(row.station, 0), row.station),
            "unlock_level": row.unlock_level,
            "grade": row.grade,
            "category": row.primary_class,
            "sub_category": row.second_class_cn,
            "pic_url": row.pic_url,
            "period_hours": row.period_hours,
            "market_price": row.market_price,
            "fee": row.fee,
            "profit": row.profit,
            "profit_per_hour": row.profit_per_hour,
            "origin": row.origin,
            "fetched_at": _iso(row.fetched_at),
        }
        for row in session.scalars(
            select(ManufactureProfit).where(ManufactureProfit.source == active_source)
        )
    ]

    last_run = session.scalars(select(CollectRun).order_by(CollectRun.id.desc()).limit(1)).first()
    priced = [row for row in items if row["price"] is not None]
    summary = {
        "item_count": len(items),
        "tradable_count": sum(1 for row in items if row["is_tradable"]),
        "priced_count": len(priced),
        "rising_count": sum(1 for row in priced if (row["bl_today"] or 0) > 0),
        "falling_count": sum(1 for row in priced if (row["bl_today"] or 0) < 0),
        "flat_count": sum(1 for row in priced if row["bl_today"] == 0),
        "stale_count": sum(1 for row in items if row["is_stale"]),
        "data_source": active_source,
        "last_collect": _run_to_dict(last_run),
        "generated_at": _iso(utcnow()),
    }

    sizes = {
        "items.json": _write_json(DATA_DIR / "items.json", items),
        "history.json": _write_json(DATA_DIR / "history.json", history),
        "manufacture.json": _write_json(DATA_DIR / "manufacture.json", manufacture),
        "summary.json": _write_json(DATA_DIR / "summary.json", summary),
    }
    meta = {
        "generated_at": summary["generated_at"],
        "item_count": summary["item_count"],
        "priced_count": summary["priced_count"],
        "manufacture_count": len(manufacture),
        "history_days": HISTORY_DAYS,
        "history_points": sum(len(points) for points in history.values()),
        "data_source": active_source,
        "app_version": __version__,
    }
    sizes["meta.json"] = _write_json(DATA_DIR / "meta.json", meta)
    return sizes


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds") + "Z"


def _run_to_dict(run: CollectRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "source": run.source,
        "status": run.status,
        "items_ok": run.items_ok,
        "items_failed": run.items_failed,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "error": run.error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="导出静态数据供 GitHub Pages 使用")
    parser.add_argument(
        "--no-collect",
        action="store_true",
        help="跳过联网采集，只用现有数据库重新导出（不消耗平台资源）",
    )
    args = parser.parse_args()

    init_db()
    session = SessionLocal()
    try:
        seeded_items, seeded_snapshots = seed_from_previous_export(session)
        print(f"1) 用上次导出预热：物品 {seeded_items} 个，历史快照 {seeded_snapshots} 条")

        if args.no_collect:
            print("2) 已跳过采集（--no-collect）")
        else:
            print("2) 采集与同步…")
            collect(session)

        sizes = export(session)
        print("3) 导出完成：")
        for name, size in sizes.items():
            print(f"   {name:<18} {size / 1024:8.1f} KB")
        print(f"   输出目录：{DATA_DIR}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
