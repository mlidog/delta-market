/** 与后端 `app/api/routes/items.py` 的 SortField 保持一致。 */
export const SORT_OPTIONS = [
  { value: "bl_today", label: "今日涨跌（平台）" },
  { value: "change_prev_pct", label: "较上次采集" },
  { value: "change_24h_pct", label: "较 24 小时前" },
  { value: "change_7d_pct", label: "较 7 天前" },
  { value: "day_3_bl", label: "3 日涨跌（平台）" },
  { value: "day_7_bl", label: "7 日涨跌（平台）" },
  { value: "day_30_bl", label: "30 日涨跌（平台）" },
  { value: "price", label: "当前价格" },
  { value: "price_per_slot", label: "单格价值" },
  { value: "grade", label: "等级" },
  { value: "name", label: "名称" },
] as const;

/** 数据帝的一级分类（`primaryClass`）。 */
export const CATEGORY_OPTIONS = [
  { value: "", label: "全部分类" },
  { value: "gun", label: "枪械" },
  { value: "ammo", label: "子弹" },
  { value: "acc", label: "配件" },
  { value: "protect", label: "防护装备" },
  { value: "collection", label: "收集品" },
  { value: "consume", label: "消耗品" },
  { value: "key", label: "钥匙卡" },
] as const;

export const CATEGORY_LABELS: Record<string, string> = {
  gun: "枪械",
  ammo: "子弹",
  acc: "配件",
  protect: "防护装备",
  collection: "收集品",
  consume: "消耗品",
  key: "钥匙卡",
};

export const PAGE_SIZES = [20, 50, 100, 200] as const;
