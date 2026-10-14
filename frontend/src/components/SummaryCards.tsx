import { useState } from "react";

import type { DashboardSummary, ItemPrice } from "../api/types";
import { MOVER_LIMIT } from "../constants";
import {
  changeClass,
  formatCollectTime,
  formatDateTime,
  formatNumber,
  formatPercent,
} from "../utils/format";

export interface MoverGroup {
  key: string;
  label: string;
  /** 已按"今日价格差绝对值"从大到小排序 */
  items: ItemPrice[];
}

interface Props {
  summary: DashboardSummary | null;
  loading: boolean;
  movers: MoverGroup[];
  /** 点开列表里的物品：跳转到行情表对应位置并显示曲线 */
  onPick: (item: ItemPrice) => void;
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

/** 图标：加载失败就留白，不要出现浏览器默认的破图图标。 */
function ItemIcon({ url, size }: { url: string | null; size: number }) {
  const [failed, setFailed] = useState(false);
  const style = { width: size, height: size };
  if (!url || failed) {
    return <div className="mover-icon mover-icon-empty" style={style} aria-hidden="true" />;
  }
  return (
    <img
      className="mover-icon"
      style={style}
      src={url}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

/** 「补货价 → 最高价」那一行的公共渲染：两个价格都带上采样时间。 */
function PriceLine({
  label,
  price,
  at,
}: {
  label: string;
  price: number | null;
  at: string | null;
}) {
  return (
    <div className="mover-line">
      <span className="mover-line-label">{label}</span>
      <b>{formatNumber(price)}</b>
      <i>{formatCollectTime(at) || "—"}</i>
    </div>
  );
}

function MoverCard({ group, onPick }: { group: MoverGroup; onPick: (item: ItemPrice) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [top] = group.items;

  return (
    <div className={`card mover-card${expanded ? " mover-card-open" : ""}`}>
      <div className="card-label">
        {group.label}
        <span className="mover-tag">最高价 − 补货价</span>
      </div>

      {top === undefined ? (
        <div className="card-hint">暂无数据</div>
      ) : (
        <>
          <div className="mover-row mover-row-top">
            <ItemIcon url={top.pic_url} size={40} />
            <div className="mover-main">
              <div className="item-name">{top.name}</div>
              <div className="mover-spread">
                <span className="mover-spread-value">{formatNumber(top.day_spread)}</span>
                <em className={changeClass(top.bl_today)}>
                  平台今日 {formatPercent(top.bl_today)}
                </em>
              </div>
              <div className="mover-lines">
                <PriceLine label="补货" price={top.restock_price} at={top.restock_at} />
                <PriceLine label="最高" price={top.day_high} at={top.day_high_at} />
              </div>
            </div>
          </div>

          {group.items.length > 1 && (
            <button className="chip mover-toggle" onClick={() => setExpanded((open) => !open)}>
              {expanded ? "收起" : `展开（共 ${group.items.length} 个，最多 ${MOVER_LIMIT}）`}
            </button>
          )}

          {expanded && (
            /* 覆盖式列表：绝对定位浮在卡片下方，不撑开卡片、不影响主页面布局 */
            <div className="mover-overlay">
              <div className="mover-overlay-head">
                <span>按「最高价 − 补货价」从大到小</span>
                <button className="chip" onClick={() => setExpanded(false)}>
                  关闭
                </button>
              </div>
              <ol className="mover-overlay-list">
                {group.items.map((item) => (
                  <li
                    key={item.item_id}
                    title="点击跳转到物品行情并显示曲线"
                    onClick={() => {
                      setExpanded(false);
                      onPick(item);
                    }}
                  >
                    <ItemIcon url={item.pic_url} size={24} />
                    <span className="mover-list-name">{item.name}</span>
                    <span className="mover-list-price">
                      {formatNumber(item.restock_price)} → {formatNumber(item.day_high)}
                      <i>{formatCollectTime(item.day_high_at)}</i>
                    </span>
                    <span className="mover-list-change">
                      {formatNumber(item.day_spread)}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function SummaryCards({ summary, loading, movers, onPick }: Props) {
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

        {movers.map((group) => (
          <MoverCard key={group.key} group={group} onPick={onPick} />
        ))}
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
