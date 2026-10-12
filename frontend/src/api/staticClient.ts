/**
 * 静态版 API 适配层（GitHub Pages 用）。
 *
 * Pages 上没有后端，所有数据都是构建时导出的 JSON。这个模块把相同的
 * `api` 接口在浏览器里实现一遍——筛选、排序、分页规则与后端保持一致
 * （空值排最后、涨幅榜降权收集品与钥匙卡、制造榜同物品只留最高等级）。
 */

import type {
  DashboardSummary,
  Health,
  HistoryPeriod,
  ItemHistoryResponse,
  ItemListResponse,
  ItemPrice,
  ItemQuery,
  ManufactureItem,
  ManufactureListResponse,
  ManufactureQuery,
} from "./types";

const BASE = import.meta.env.BASE_URL || "/";
const DATA_DIR = `${BASE}data`;

/** 涨幅类排序：与后端一致，这些排序会把收集品与钥匙卡沉到后面 */
const CHANGE_SORTS = new Set([
  "bl_today",
  "day_3_bl",
  "day_7_bl",
  "day_30_bl",
  "change_prev_pct",
  "change_24h_pct",
  "change_7d_pct",
]);

const DEPRIORITIZED = new Set(["collection", "key", "收集品", "钥匙", "钥匙卡"]);

const PERIOD_MS: Record<HistoryPeriod, number> = {
  "1h": 3_600_000,
  "24h": 86_400_000,
  "7d": 604_800_000,
  "30d": 2_592_000_000,
};

interface Meta {
  generated_at: string;
  item_count: number;
  history_points: number;
  data_source: string;
  app_version: string;
}

let itemsPromise: Promise<ItemPrice[]> | null = null;
let manufacturePromise: Promise<ManufactureItem[]> | null = null;
let historyPromise: Promise<Record<string, [number, number][]>> | null = null;
let summaryPromise: Promise<DashboardSummary> | null = null;
let metaPromise: Promise<Meta> | null = null;

async function loadJson<T>(name: string): Promise<T> {
  const response = await fetch(`${DATA_DIR}/${name}`);
  if (!response.ok) {
    throw new Error(`静态数据加载失败：data/${name}（HTTP ${response.status}）`);
  }
  return (await response.json()) as T;
}

const loadItems = () => (itemsPromise ??= loadJson<ItemPrice[]>("items.json"));
const loadSummary = () => (summaryPromise ??= loadJson<DashboardSummary>("summary.json"));
const loadMeta = () => (metaPromise ??= loadJson<Meta>("meta.json"));
const loadManufacture = () =>
  (manufacturePromise ??= loadJson<ManufactureItem[]>("manufacture.json"));
const loadHistory = () =>
  (historyPromise ??= loadJson<Record<string, [number, number][]>>("history.json"));

/** 与后端 `_sort_rows` 同规则：空值最后，涨幅榜再降权特定分类。 */
function sortItems(rows: ItemPrice[], field: string, order: "asc" | "desc"): void {
  const isText = field === "name";
  rows.sort((a, b) => {
    const left = (a as unknown as Record<string, unknown>)[field];
    const right = (b as unknown as Record<string, unknown>)[field];
    const norm = (value: unknown) => (value === null || value === undefined ? (isText ? "" : 0) : value);
    const l = norm(left);
    const r = norm(right);
    const cmp = isText
      ? String(l).localeCompare(String(r), "zh-CN")
      : Number(l) - Number(r);
    return order === "desc" ? -cmp : cmp;
  });
  const missing = (row: ItemPrice) =>
    (row as unknown as Record<string, unknown>)[field] === null ? 1 : 0;
  rows.sort((a, b) => missing(a) - missing(b));
  if (CHANGE_SORTS.has(field)) {
    const deprioritized = (row: ItemPrice) =>
      DEPRIORITIZED.has(row.sub_category_code ?? "") || DEPRIORITIZED.has(row.sub_category ?? "")
        ? 1
        : 0;
    rows.sort((a, b) => deprioritized(a) - deprioritized(b));
  }
}

/** 与后端 `list_items` 同规则。 */
function filterItems(rows: ItemPrice[], query: ItemQuery): ItemPrice[] {
  const keyword = (query.search ?? "").trim().toLowerCase();
  return rows.filter((item) => {
    if (query.category && item.category !== query.category) return false;
    if (query.sub_category) {
      const hit =
        item.sub_category === query.sub_category ||
        item.sub_category_code === query.sub_category;
      if (!hit) return false;
    }
    if (query.grade !== undefined && item.grade !== query.grade) return false;
    if (query.tradable !== undefined && item.is_tradable !== query.tradable) return false;
    if (keyword && !item.name.toLowerCase().includes(keyword)) return false;
    return true;
  });
}

/** 与后端 `_highest_level_only` 同规则：同物品只留最高等级。 */
function dedupeLevels(rows: ManufactureItem[]): ManufactureItem[] {
  const highest = new Map<string, number>();
  for (const row of rows) {
    const key = `${row.station}|${row.item_key}`;
    highest.set(key, Math.max(highest.get(key) ?? 0, row.unlock_level));
  }
  return rows.filter((row) => highest.get(`${row.station}|${row.item_key}`) === row.unlock_level);
}

function sortManufacture(
  rows: ManufactureItem[],
  field: string,
  order: "asc" | "desc",
): void {
  const isText = field === "name";
  rows.sort((a, b) => {
    const norm = (value: unknown) => (value === null || value === undefined ? (isText ? "" : 0) : value);
    const l = norm((a as unknown as Record<string, unknown>)[field]);
    const r = norm((b as unknown as Record<string, unknown>)[field]);
    const cmp = isText ? String(l).localeCompare(String(r), "zh-CN") : Number(l) - Number(r);
    return order === "desc" ? -cmp : cmp;
  });
  const missing = (row: ManufactureItem) =>
    (row as unknown as Record<string, unknown>)[field] === null ? 1 : 0;
  rows.sort((a, b) => missing(a) - missing(b));
}

export const staticApi = {
  health: async (): Promise<Health> => {
    const meta = await loadMeta();
    return {
      status: "ok",
      app: "三角洲物价观察（静态版）",
      version: meta.app_version,
      database: "static",
      data_source: meta.data_source,
      scheduler_running: false,
      next_collect_at: null,
      server_time: meta.generated_at,
    };
  },

  summary: () => loadSummary(),

  items: async (query: ItemQuery): Promise<ItemListResponse> => {
    const rows = sortBy(
      filterItems(await loadItems(), query),
      query.sort ?? "price",
      query.order ?? "desc",
    );
    const offset = query.offset ?? 0;
    const limit = query.limit ?? 50;
    return { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset };
  },

  history: async (itemId: string, period: HistoryPeriod): Promise<ItemHistoryResponse> => {
    const [history, items] = await Promise.all([loadHistory(), loadItems()]);
    const raw = (history[itemId] ?? []).map(([stamp, price]) => ({
      t: new Date(stamp * 1000).toISOString(),
      price,
    }));
    const anchor = raw.length > 0 ? new Date(raw[raw.length - 1].t).getTime() : Date.now();
    const points = raw.filter((point) => new Date(point.t).getTime() >= anchor - PERIOD_MS[period]);
    const name = items.find((item) => item.item_id === itemId)?.name ?? itemId;
    const change =
      points.length >= 2 && points[0].price !== 0
        ? Math.round(((points[points.length - 1].price - points[0].price) / points[0].price) * 10000) / 100
        : null;
    return {
      item_id: itemId,
      name,
      period,
      point_count: points.length,
      change_pct: change,
      points,
    };
  },

  manufacture: async (query: ManufactureQuery): Promise<ManufactureListResponse> => {
    const origin = query.origin ?? "pro";
    let rows = (await loadManufacture()).filter((row) => row.origin === origin);
    if (query.station) rows = rows.filter((row) => row.station === query.station);
    if (query.level !== undefined) {
      rows = rows.filter((row) => row.unlock_level === query.level);
    } else {
      rows = dedupeLevels(rows);
    }
    sortManufacture(rows, query.sort ?? "profit_per_hour", query.order ?? "desc");
    const offset = query.offset ?? 0;
    const limit = query.limit ?? 5;
    return {
      items: rows.slice(offset, offset + limit),
      total: rows.length,
      limit,
      offset,
      stations: [],
      levels: [1, 2, 3],
      origin,
      source: "static",
      fetched_at: (await loadManufacture())[0]?.fetched_at ?? null,
    };
  },

  manufactureByStation: async (): Promise<never> => {
    throw new Error("静态版请使用 manufacture 接口按站点分别取数");
  },

  manufactureSync: async (): Promise<never> => {
    throw new Error("静态版没有后端，无法手动同步；数据由 GitHub Actions 定时更新。");
  },
};

function sortBy(rows: ItemPrice[], field: string, order: "asc" | "desc"): ItemPrice[] {
  const copy = [...rows];
  sortItems(copy, field, order);
  return copy;
}
