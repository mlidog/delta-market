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

/**
 * 分类筛选项。
 *
 * 真实数据里 `primaryClass` 只有 5 种（gun / ammo / acc / protect / props），
 * 钥匙卡、收集品、消耗品都归在 `props` 下、靠二级分类区分，
 * 所以这三个选项要走 `sub_category` 过滤。
 */
export const CATEGORY_OPTIONS = [
  { value: "", label: "全部分类", field: "none" },
  { value: "gun", label: "枪械", field: "category" },
  { value: "ammo", label: "子弹", field: "category" },
  { value: "acc", label: "配件", field: "category" },
  { value: "protect", label: "防护装备", field: "category" },
  { value: "props", label: "道具", field: "category" },
  { value: "key", label: "钥匙卡", field: "sub" },
  { value: "collection", label: "收集品", field: "sub" },
  { value: "consume", label: "消耗品", field: "sub" },
] as const;

/** 把下拉框选中的值翻译成接口参数。 */
export function categoryQuery(value: string): {
  category?: string;
  sub_category?: string;
} {
  const option = CATEGORY_OPTIONS.find((item) => item.value === value);
  if (option === undefined || option.field === "none") return {};
  return option.field === "category"
    ? { category: option.value }
    : { sub_category: option.value };
}

export const CATEGORY_LABELS: Record<string, string> = {
  gun: "枪械",
  ammo: "子弹",
  acc: "配件",
  protect: "防护装备",
  props: "道具",
  collection: "收集品",
  consume: "消耗品",
  key: "钥匙卡",
};

/** 数据帝的兜底分类 `props` 下二级分类才是真正的含义，这里补上中文。 */
export const SUBCATEGORY_LABELS: Record<string, string> = {
  collection: "收集品",
  key: "钥匙卡",
  consume: "消耗品",
};

export function categoryLabel(category: string | null): string {
  if (!category) return "—";
  return CATEGORY_LABELS[category] ?? category;
}

export function subCategoryLabel(subCategory: string | null): string {
  if (!subCategory) return "";
  return SUBCATEGORY_LABELS[subCategory] ?? subCategory;
}

export const PAGE_SIZES = [20, 50, 100, 200] as const;
