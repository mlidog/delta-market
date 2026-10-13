import { useEffect, useState } from "react";

import { api } from "../api";
import type { HistoryPeriod, ItemHistoryResponse, ItemPrice } from "../api/types";
import { changeClass, formatNumber, formatPercent } from "../utils/format";
import PriceChart from "./PriceChart";

const PERIODS: HistoryPeriod[] = ["1h", "24h", "7d", "30d"];

interface Props {
  /** 主图：你点选的物品；没点选时是今日涨幅榜首 */
  primary: ItemPrice;
  primaryLabel: string;
  /** 副图：今日跌幅榜首（固定作为参照） */
  secondary: ItemPrice | null;
  period: HistoryPeriod;
  onPeriodChange: (period: HistoryPeriod) => void;
}

function ChartBlock({
  item,
  period,
  label,
}: {
  item: ItemPrice;
  period: HistoryPeriod;
  label: string;
}) {
  const [history, setHistory] = useState<ItemHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setHistory(null);
    setError(null);
    api
      .history(item.item_id, period)
      .then((response) => {
        if (!cancelled) setHistory(response);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [item.item_id, period]);

  return (
    <div className="chart-block">
      <div className="chart-block-head">
        <div className="chart-block-title">
          <div className="item-name">{item.name}</div>
          <div className="item-id">
            {label}
            {item.sub_category ? ` · ${item.sub_category}` : ""}
          </div>
        </div>
        <div className="chart-block-price">
          <span>{formatNumber(item.price)}</span>
          <span className={changeClass(item.bl_today)}>{formatPercent(item.bl_today)}</span>
        </div>
      </div>
      {history !== null && (
        <div className="chart-block-meta">
          区间 {formatPercent(history.change_pct)} · {history.point_count} 个快照
          {item.is_stale ? " · 旧价" : ""}
        </div>
      )}
      <PriceChart history={history} loading={history === null} error={error} />
    </div>
  );
}

/** 右侧固定的价格曲线栏：主图 + 跌幅榜首参照图。 */
export default function ChartPanel({
  primary,
  primaryLabel,
  secondary,
  period,
  onPeriodChange,
}: Props) {
  return (
    <aside className="panel chart-column">
      <div className="panel-head">
        <h2>价格曲线</h2>
        <div className="periods">
          {PERIODS.map((option) => (
            <button
              key={option}
              className={option === period ? "chip chip-active" : "chip"}
              onClick={() => onPeriodChange(option)}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <ChartBlock item={primary} period={period} label={primaryLabel} />
      {secondary !== null && secondary.item_id !== primary.item_id && (
        <ChartBlock item={secondary} period={period} label="今日跌幅榜首（参照）" />
      )}
    </aside>
  );
}
