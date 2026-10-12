import { useState } from "react";

import type { ItemPrice } from "../api/types";
import { changeClass, formatNumber, formatPercent } from "../utils/format";
import HoverChart from "./HoverChart";

export interface BoardData {
  metric: "change_24h_pct" | "bl_today";
  gainers: ItemPrice[];
  losers: ItemPrice[];
}

interface Props {
  board: BoardData;
  open: boolean;
  onToggle: () => void;
  onSelect: (item: ItemPrice) => void;
}

/** 展开 / 收起时每个榜显示多少条 */
const FULL_COUNT = 10;
const PREVIEW_COUNT = 5;

function boardValue(item: ItemPrice, metric: BoardData["metric"]): number | null {
  return metric === "change_24h_pct" ? item.change_24h_pct : item.bl_today;
}

export default function PriceBoard({ board, open, onToggle, onSelect }: Props) {
  const [hover, setHover] = useState<{ item: ItemPrice; x: number; y: number } | null>(null);

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>
            {board.metric === "change_24h_pct" ? "24 小时涨跌榜" : "今日涨跌榜"}
            <span className="item-id">
              {" "}
              各 {open ? FULL_COUNT : PREVIEW_COUNT} 件 · 悬停看曲线，点击看详情
            </span>
          </h2>
          <div className="tabs">
            {board.metric === "bl_today" && (
              <span className="muted" style={{ fontSize: 12 }}>
                本地历史不足 24 小时，暂用平台「今日涨跌」
              </span>
            )}
            <button className="chip" onClick={onToggle}>
              {open ? "收起" : "展开"}
            </button>
          </div>
        </div>

        <div className="board-grid">
          {[
            { title: "涨幅最大", rows: board.gainers },
            { title: "跌幅最大", rows: board.losers },
          ].map((column) => {
            const rows = open ? column.rows : column.rows.slice(0, PREVIEW_COUNT);
            return (
              <div key={column.title} className="board-column">
                <h3>
                  {column.title}
                  {!open && column.rows.length > PREVIEW_COUNT && (
                    <span className="item-id"> 前 {PREVIEW_COUNT} 条</span>
                  )}
                </h3>
                <ol>
                  {rows.map((item) => {
                    const value = boardValue(item, board.metric);
                    return (
                      <li
                        key={item.item_id}
                        onMouseEnter={(event) =>
                          setHover({ item, x: event.clientX, y: event.clientY })
                        }
                        onMouseMove={(event) =>
                          setHover({ item, x: event.clientX, y: event.clientY })
                        }
                        onMouseLeave={() => setHover(null)}
                        onClick={() => {
                          setHover(null);
                          onSelect(item);
                        }}
                      >
                        <span className="board-name">{item.name}</span>
                        <span className="board-price">{formatNumber(item.price)}</span>
                        <span className={`board-change ${changeClass(value)}`}>
                          {formatPercent(value)}
                        </span>
                      </li>
                    );
                  })}
                </ol>
              </div>
            );
          })}
        </div>

        {!open && (
          // 收起状态仍保留前五条，这里只提示还有多少没显示
          <div className="board-summary">
            <span className="muted">
              已收起：每榜显示前 {PREVIEW_COUNT} 条，完整榜单各 {FULL_COUNT} 条
            </span>
          </div>
        )}
      </section>

      <HoverChart
        item={open ? (hover?.item ?? null) : null}
        x={hover?.x ?? 0}
        y={hover?.y ?? 0}
        metric={board.metric}
      />
    </>
  );
}
