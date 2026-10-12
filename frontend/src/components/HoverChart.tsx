import { LineChart } from "echarts/charts";
import { GridComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import type { ItemHistoryResponse, ItemPrice } from "../api/types";
import { changeClass, formatNumber, formatPercent } from "../utils/format";

echarts.use([LineChart, GridComponent, CanvasRenderer]);

/** 悬停小窗的曲线缓存：同一物品反复悬停不重复请求 */
const historyCache = new Map<string, ItemHistoryResponse>();

interface Props {
  /** 当前悬停的物品；null 表示不显示小窗 */
  item: ItemPrice | null;
  x: number;
  y: number;
  /** 涨跌榜当前用的口径，用来显示对应的涨跌幅 */
  metric: "change_24h_pct" | "bl_today";
}

export default function HoverChart({ item, x, y, metric }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const [history, setHistory] = useState<ItemHistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const itemId = item?.item_id ?? null;

  useEffect(() => {
    if (itemId === null) {
      setHistory(null);
      return;
    }
    const cached = historyCache.get(itemId);
    if (cached !== undefined) {
      setHistory(cached);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setHistory(null);
    setLoading(true);
    api
      .history(itemId, "24h")
      .then((response) => {
        historyCache.set(itemId, response);
        if (!cancelled) setHistory(response);
      })
      .catch(() => {
        if (!cancelled) setHistory(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [itemId]);

  useEffect(() => {
    const container = chartRef.current;
    if (container === null || history === null || history.points.length < 2) {
      return;
    }
    const chart = echarts.init(container);
    const prices = history.points.map((point) => point.price);
    const rising = prices[prices.length - 1] >= prices[0];
    const color = rising ? "#e5484d" : "#30a46c";

    chart.setOption({
      animation: false,
      grid: { left: 4, right: 4, top: 6, bottom: 4 },
      xAxis: {
        type: "category",
        data: history.points.map((point) => point.t),
        show: false,
        boundaryGap: false,
      },
      yAxis: { type: "value", scale: true, show: false },
      series: [
        {
          type: "line",
          smooth: true,
          showSymbol: false,
          data: prices,
          lineStyle: { width: 1.6, color },
          itemStyle: { color },
          areaStyle: { color: rising ? "rgba(229,72,77,0.15)" : "rgba(48,164,108,0.15)" },
        },
      ],
    });
    return () => chart.dispose();
  }, [history]);

  if (item === null) {
    return null;
  }

  // 贴着光标显示；靠近右/下边缘时回收，避免跑出屏幕
  const width = 260;
  const left = Math.max(8, Math.min(x + 16, window.innerWidth - width - 12));
  const top = Math.max(8, Math.min(y + 16, window.innerHeight - 170));
  const value = metric === "change_24h_pct" ? item.change_24h_pct : item.bl_today;
  const ready = history !== null && history.points.length >= 2;

  return (
    <div className="hover-card" style={{ left, top, width }}>
      <div className="hover-card-head">
        <span className="hover-card-name">{item.name}</span>
        <span className={changeClass(value)}>{formatPercent(value)}</span>
      </div>
      <div className="hover-card-meta">
        24 小时 · {ready ? `${history.point_count} 个快照` : loading ? "加载中" : "快照不足"}
        {ready && history.change_pct !== null && (
          <>
            {" "}
            · 区间 {formatNumber(history.points[0].price)} →{" "}
            {formatNumber(history.points[history.points.length - 1].price)}
          </>
        )}
      </div>
      {ready ? (
        <div ref={chartRef} className="hover-chart" />
      ) : (
        <div className="hover-chart hover-chart-empty">
          {loading ? "加载曲线…" : "这个物品还没有足够的快照"}
        </div>
      )}
    </div>
  );
}
