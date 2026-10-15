/** 与后端 `app/api/routes/items.py` 的 SortField 保持一致。 */
export const SORT_OPTIONS = [
  { value: "bl_today", label: "今日涨跌（平台）" },
  { value: "price_delta", label: "今日价差（绝对值）" },
  { value: "spread_24h", label: "24h 价差（最高价−补货价）" },
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

export function categoryLabel(category: string | null): string {
  if (!category) return "—";
  return CATEGORY_LABELS[category] ?? category;
}

/**
 * 二级分类只在拿到中文名时才展示。
 *
 * 数据帝那两个二级分类字段一个放中文名、一个放代码（接口层已经换成中文名）；
 * 万一上游缺中文名只剩代码，这里宁可留空，也不要把 accBarrel 这类代码丢给用户。
 */
export function subCategoryLabel(subCategory: string | null): string {
  if (!subCategory) return "";
  return /[^\x00-\x7F]/.test(subCategory) ? subCategory : "";
}

export const PAGE_SIZES = [20, 50, 100, 200] as const;

/** 特勤处站点，顺序与后端 `STATION_KEYS` 保持一致。 */
export const MANUFACTURE_STATIONS = [
  { key: "tech", label: "技术中心" },
  { key: "workbench", label: "工作台" },
  { key: "pharmacy", label: "制药台" },
  { key: "armor", label: "防具台" },
] as const;

/** 制造排行每页条数。 */
export const MANUFACTURE_PAGE_SIZE = 5;

/** 顶部卡片关注的三个分类（今日变动最大的物品） */
export const MOVER_CATEGORIES = [
  { key: "protect", label: "防护道具" },
  { key: "gun", label: "枪械" },
  { key: "ammo", label: "子弹" },
] as const;

/** 每个分类最多展示多少条 */
export const MOVER_LIMIT = 10;

/**
 * 顶部卡片的**取数条数**：要多取一些——下面会剔除 H70 / HA-2 整族（每族 3 个变体），
 * 过滤后仍要凑满 MOVER_LIMIT 条。
 */
export const MOVER_FETCH_LIMIT = 40;

/**
 * 顶部卡片里完全屏蔽的装备名（**本体和所有耐久细分项都不显示**）。
 *
 * 同一件防具在交易行里有 本体 / (几乎全新) / (破损) 等多个条目，
 * 它们会一口气占掉防护道具卡片的前几名（H70 精英头盔、HA-2重型防弹衣 就是这种），
 * 所以按前缀把整族（含本体）都挡掉，让卡片显示其它物品。
 * 只影响顶部卡片，物品行情表里照常显示它们。
 */
export const EXCLUDED_MOVER_PREFIXES = ["H70 精英头盔", "HA-2重型防弹衣"] as const;

export function isExcludedMoverName(name: string): boolean {
  return EXCLUDED_MOVER_PREFIXES.some((prefix) => name.startsWith(prefix));
}

/** 与后端 `CHANGE_SORT_FIELDS` 保持一致：这些排序会降权收集品与钥匙卡。 */
export const CHANGE_SORT_VALUES = new Set([
  "bl_today",
  "day_3_bl",
  "day_7_bl",
  "day_30_bl",
  "change_prev_pct",
  "change_24h_pct",
  "change_7d_pct",
]);
