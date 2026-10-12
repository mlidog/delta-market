import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import type { ItemHistoryResponse } from "../api/types";
import { formatAxisTime, formatNumber } from "../utils/format";

// 只引入用到的模块，避免整包 ECharts 进产物
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

interface Props {
  history: ItemHistoryResponse | null;
  loading: boolean;
  error: string | null;
}

export default function PriceChart({ history, loading, error }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null || history === null || history.points.length === 0) {
      return;
    }

    const chart = echarts.init(container);
    const prices = history.points.map((point) => point.price);
    const rising = prices[prices.length - 1] >= prices[0];
    const lineColor = rising ? "#e5484d" : "#30a46c";

    chart.setOption({
      grid: { left: 76, right: 24, top: 24, bottom: 44 },
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: number) => formatNumber(value),
        axisPointer: { type: "line" },
      },
      xAxis: {
        type: "category",
        data: history.points.map((point) => point.t),
        boundaryGap: false,
        axisLabel: { formatter: (value: string) => formatAxisTime(value), hideOverlap: true },
        axisLine: { lineStyle: { color: "#dfe2e7" } },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { formatter: (value: number) => formatNumber(value) },
        splitLine: { lineStyle: { type: "dashed", color: "#eceef1" } },
      },
      series: [
        {
          name: history.name,
          type: "line",
          smooth: true,
          showSymbol: history.points.length <= 60,
          symbolSize: 6,
          data: prices,
          lineStyle: { width: 2, color: lineColor },
          itemStyle: { color: lineColor },
          areaStyle: {
            color: rising ? "rgba(229,72,77,0.18)" : "rgba(48,164,108,0.18)",
          },
        },
      ],
    });

    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.dispose();
    };
  }, [history]);

  if (error !== null) {
    return <div className="empty">历史数据加载失败：{error}</div>;
  }
  if (history === null) {
    return <div className="chart-placeholder">{loading ? "加载中…" : "请选择一个物品"}</div>;
  }
  if (history.points.length === 0) {
    return <div className="empty">这个物品还没有历史快照，多采集几次再看。</div>;
  }

  return <div ref={containerRef} className="chart" />;
}
