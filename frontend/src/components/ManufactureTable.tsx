import type { ManufactureItem } from "../api/types";
import { formatNumber } from "../utils/format";

interface Props {
  items: ManufactureItem[];
  loading: boolean;
  rankBy: "profit" | "profit_per_hour";
}

/** 收益永远用绝对色：正红负绿（中国习惯），与涨跌幅配色一致。 */
function profitClass(value: number | null): string {
  if (value === null) return "muted";
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

export default function ManufactureTable({ items, loading, rankBy }: Props) {
  if (!loading && items.length === 0) {
    return (
      <div className="empty">
        还没有制造收益数据。点右上角「同步制造收益」拉一次（会消耗平台资源）。
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th className="col-name">制造产物</th>
            <th>站点</th>
            <th className="num">等级</th>
            <th className="num">时长(h)</th>
            <th className="num">总收益</th>
            <th className="num">每小时</th>
            <th className="num">推算材料成本</th>
            <th className="num">参考价</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={`${item.item_key}-${item.station}-${item.unlock_level}`}>
              <td className="num muted">{index + 1}</td>
              <td className="col-name">
                <div className="item-name">{item.name}</div>
                <div className="item-id">
                  {item.sub_category ?? ""} {item.grade === null ? "" : `· ${item.grade} 级`}
                </div>
              </td>
              <td>{item.station_label}</td>
              <td className="num">{item.unlock_level || "—"}</td>
              <td className="num">{item.period_hours === null ? "—" : item.period_hours}</td>
              <td className={`num ${rankBy === "profit" ? "strong" : ""} ${profitClass(item.profit)}`}>
                {formatNumber(item.profit)}
              </td>
              <td
                className={`num ${rankBy === "profit_per_hour" ? "strong" : ""} ${profitClass(
                  item.profit_per_hour,
                )}`}
              >
                {formatNumber(item.profit_per_hour)}
              </td>
              <td className="num muted">{formatNumber(item.implied_material_cost)}</td>
              <td className="num">{formatNumber(item.market_price)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
