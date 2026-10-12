import type { DashboardSummary } from "../api/types";
import { formatDateTime, formatNumber } from "../utils/format";

interface Props {
  summary: DashboardSummary | null;
  loading: boolean;
}

export function statusLabel(status: string): string {
  switch (status) {
    case "success":
      return "成功";
    case "partial":
      return "部分成功";
    case "failed":
      return "失败";
    case "running":
      return "进行中";
    default:
      return status;
  }
}

export default function SummaryCards({ summary, loading }: Props) {
  if (loading && summary === null) {
    return (
      <div className="summary-grid">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="card skeleton" />
        ))}
      </div>
    );
  }
  if (summary === null) {
    return null;
  }

  const last = summary.last_collect;
  const failed = last !== undefined && last !== null && last.status !== "success";

  return (
    <>
      <div className="summary-grid">
        <div className="card">
          <div className="card-label">物品总数</div>
          <div className="card-value">{formatNumber(summary.item_count)}</div>
          <div className="card-hint">可交易 {formatNumber(summary.tradable_count)}</div>
        </div>
        <div className="card">
          <div className="card-label">今日上涨</div>
          <div className="card-value up">{formatNumber(summary.rising_count)}</div>
          <div className="card-hint">有价格 {formatNumber(summary.priced_count)} 个</div>
        </div>
        <div className="card">
          <div className="card-label">今日下跌</div>
          <div className="card-value down">{formatNumber(summary.falling_count)}</div>
          <div className="card-hint">持平 {formatNumber(summary.flat_count)} 个</div>
        </div>
        <div className="card">
          <div className="card-label">最近一次采集</div>
          <div className={`card-value ${failed ? "warn" : last ? "up" : "muted"}`}>
            {last ? statusLabel(last.status) : "尚无记录"}
          </div>
          <div className="card-hint">
            {last
              ? `${formatDateTime(last.started_at)} · 成功 ${last.items_ok}`
              : "等待首次采集"}
          </div>
        </div>
      </div>
      {(summary.stale_count > 0 || failed) && (
        <div className="alert">
          有 {summary.stale_count} 个物品仍在展示旧价
          {last?.error ? `（原因：${last.error}）` : ""}
        </div>
      )}
    </>
  );
}
