import type { ItemPrice } from "../api/types";
import { categoryLabel, subCategoryLabel } from "../constants";
import { changeClass, formatNumber, formatPercent } from "../utils/format";

interface Props {
  items: ItemPrice[];
  selectedId: string | null;
  onSelect: (item: ItemPrice) => void;
  loading: boolean;
}

function StatusTag({ item }: { item: ItemPrice }) {
  if (item.is_stale) return <span className="tag tag-stale">旧价</span>;
  if (item.price === null) return <span className="tag tag-muted">无价格</span>;
  return <span className="tag tag-ok">正常</span>;
}

export default function ItemTable({ items, selectedId, onSelect, loading }: Props) {
  if (!loading && items.length === 0) {
    return <div className="empty">没有符合条件的物品。</div>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="col-name">物品</th>
            <th>分类</th>
            <th className="num">等级</th>
            <th className="num">当前价格</th>
            <th className="num">今日（平台）</th>
            <th className="num">较上次采集</th>
            <th className="num">较 24 小时前</th>
            <th className="num">较 7 天前</th>
            <th className="num">单格价值</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.item_id}
              className={item.item_id === selectedId ? "selected" : undefined}
              onClick={() => onSelect(item)}
            >
              <td className="col-name">
                <div className="item-name">{item.name}</div>
                <div className="item-id">{item.item_id}</div>
              </td>
              <td>
                <div>{categoryLabel(item.category)}</div>
                {item.sub_category !== null && (
                  <div className="item-id">{subCategoryLabel(item.sub_category)}</div>
                )}
              </td>
              <td className="num">{item.grade ?? "—"}</td>
              <td className="num strong">{formatNumber(item.price)}</td>
              <td className={`num ${changeClass(item.bl_today)}`}>{formatPercent(item.bl_today)}</td>
              <td className={`num ${changeClass(item.change_prev_pct)}`}>
                {formatPercent(item.change_prev_pct)}
              </td>
              <td className={`num ${changeClass(item.change_24h_pct)}`}>
                {formatPercent(item.change_24h_pct)}
              </td>
              <td className={`num ${changeClass(item.change_7d_pct)}`}>
                {formatPercent(item.change_7d_pct)}
              </td>
              <td className="num">{formatNumber(item.price_per_slot)}</td>
              <td>
                <StatusTag item={item} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
