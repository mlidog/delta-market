"""真实数据源联调脚本（会消耗平台资源，请按需运行）。

做的事：

1. 用真实 Token 完整同步一次特勤处制造收益（4 站点 × 3 等级 = 12 次请求 = 12 次资源）
2. 额外调一次官方口径接口（1 次资源），与 Pro 数据交叉校验 `price` 字段的真实含义
3. 打印总收益榜与每小时收益榜

用法：

    .\\.venv\\Scripts\\python.exe -m scripts.verify_delta

前置：`.env` 里已填好 `DELTA_API_TOKEN`。

注意必须用 `-m` 从项目根目录运行：`app` 包依赖当前目录在 `sys.path` 上。
"""

from __future__ import annotations

from sqlalchemy import select

from app.config import get_settings
from app.data_sources.delta import DeltaDataSource
from app.database import SessionLocal, init_db
from app.models import ManufactureProfit
from app.services.manufacture import sync_manufacture

ORIGIN_PRO = "pro"


def main() -> None:
    settings = get_settings()
    token = settings.delta_api_token_value
    if not token:
        raise SystemExit("未配置 DELTA_API_TOKEN，无法联调")

    init_db()
    session = SessionLocal()
    source = DeltaDataSource(
        token=token,
        base_url=settings.delta_api_base_url,
        timeout=30.0,
    )

    try:
        print("=" * 96)
        print("1) 同步特勤处制造收益（manufacturePro，4 站点 × 3 等级）")
        print("=" * 96)
        result = sync_manufacture(session, source)
        print(
            f"  写入 {result.rows} 条，请求 {result.requests} 次"
            f"（消耗 {result.requests} 次资源），成功组合 {result.station_levels}/12"
        )
        if result.errors:
            print("  错误：")
            for message in result.errors:
                print("   -", message)

        print()
        print("=" * 96)
        print("2) 交叉校验：Pro 的 price 到底是「到手价」还是「净收益」？")
        print("=" * 96)
        official = {row.item_key: row for row in source.fetch_manufacture_official(1)}
        stored = {
            row.item_key: row
            for row in session.scalars(
                select(ManufactureProfit).where(
                    ManufactureProfit.station == "tech",
                    ManufactureProfit.unlock_level == 1,
                    ManufactureProfit.origin == ORIGIN_PRO,
                )
            )
        }
        common = [key for key in official if key in stored][:6]
        print(
            f"  {'物品':<24}{'官方利润':>10}{'Pro利润':>10}{'Pro参考价':>12}"
            f"{'手续费':>8}{'时长':>7}{'反推材料成本':>14}"
        )
        for key in common:
            pro = stored[key]
            off = official[key]
            implied_cost = (pro.market_price or 0) - (pro.fee or 0) - (pro.profit or 0)
            print(
                f"  {pro.name[:22]:<24}{off.profit:>10}{pro.profit:>10}"
                f"{pro.market_price:>12}{pro.fee:>8}{pro.period_hours:>7}"
                f"{implied_cost:>14}"
            )
        matches = sum(
            1
            for key in common
            if official[key].profit is not None and official[key].profit == stored[key].profit
        )
        print(
            f"\n  同物品两家口径利润完全一致的条数：{matches}/{len(common)}"
            "  → 一致说明 Pro 的 price 与官方「利润」同义，即净收益而非售价"
        )

        print()
        print("=" * 96)
        print("3) 总收益榜 Top 10（跨全部站点与等级）")
        print("=" * 96)
        print(f"  {'物品':<26}{'站点':<8}{'等级':>4}{'时长(h)':>9}{'总收益':>12}{'每小时':>10}")
        for row in session.scalars(
            select(ManufactureProfit)
            .where(
                ManufactureProfit.origin == ORIGIN_PRO,
                ManufactureProfit.profit.is_not(None),
            )
            .order_by(ManufactureProfit.profit.desc())
            .limit(10)
        ):
            print(
                f"  {row.name[:24]:<26}{row.station:<8}{row.unlock_level:>4}"
                f"{row.period_hours:>9}{row.profit:>12,}{row.profit_per_hour:>10,}"
            )

        print()
        print("=" * 96)
        print("4) 每小时收益榜 Top 10（适合频繁上线、产线不停）")
        print("=" * 96)
        print(f"  {'物品':<26}{'站点':<8}{'等级':>4}{'时长(h)':>9}{'总收益':>12}{'每小时':>10}")
        for row in session.scalars(
            select(ManufactureProfit)
            .where(
                ManufactureProfit.origin == ORIGIN_PRO,
                ManufactureProfit.profit_per_hour.is_not(None),
            )
            .order_by(ManufactureProfit.profit_per_hour.desc())
            .limit(10)
        ):
            print(
                f"  {row.name[:24]:<26}{row.station:<8}{row.unlock_level:>4}"
                f"{row.period_hours:>9}{row.profit:>12,}{row.profit_per_hour:>10,}"
            )
    finally:
        session.close()
        source.close()


if __name__ == "__main__":
    main()
