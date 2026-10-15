/** 与后端 `app/schemas` 一一对应的类型定义。 */

export type HistoryPeriod = "1h" | "24h" | "7d" | "30d";

export interface ItemPrice {
  item_id: string;
  name: string;
  category: string | null;
  sub_category: string | null;
  sub_category_code: string | null;
  grade: number | null;
  pic_url: string | null;
  is_tradable: boolean;
  slot_w: number | null;
  slot_h: number | null;
  slot_area: number | null;
  price_per_slot: number | null;
  previous_price: number | null;
  previous_price_at: string | null;
  price: number | null;
  price_start: number | null;
  price_delta: number | null;
  /** 补货价 = 当天 0 点补货后第一条快照的价格 */
  restock_price: number | null;
  restock_at: string | null;
  /** 最近 24 小时的最高价 */
  high_24h: number | null;
  high_24h_at: string | null;
  /** 价差 = 24 小时最高价 − 补货价 */
  spread_24h: number | null;
  bl_today: number | null;
  day_3_bl: number | null;
  day_7_bl: number | null;
  day_30_bl: number | null;
  change_prev_pct: number | null;
  change_24h_pct: number | null;
  change_7d_pct: number | null;
  status: string;
  is_stale: boolean;
  source_updated_at: string | null;
  updated_at: string | null;
}

export interface ItemListResponse {
  items: ItemPrice[];
  total: number;
  limit: number;
  offset: number;
}

export interface PricePoint {
  t: string;
  price: number;
}

export interface ItemHistoryResponse {
  item_id: string;
  name: string;
  period: HistoryPeriod;
  point_count: number;
  change_pct: number | null;
  points: PricePoint[];
}

export interface CollectRunInfo {
  id: number;
  source: string;
  status: string;
  items_ok: number;
  items_failed: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface DashboardSummary {
  item_count: number;
  tradable_count: number;
  priced_count: number;
  rising_count: number;
  falling_count: number;
  flat_count: number;
  stale_count: number;
  data_source: string;
  last_collect: CollectRunInfo | null;
  generated_at: string;
}

export interface Health {
  status: string;
  app: string;
  version: string;
  database: string;
  data_source: string;
  scheduler_running: boolean;
  next_collect_at: string | null;
  server_time: string;
}

/** `/api/items` 的查询参数。 */
export interface ItemQuery {
  category?: string;
  sub_category?: string;
  search?: string;
  grade?: number;
  tradable?: boolean;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export interface ManufactureStation {
  key: string;
  label: string;
  station_id: number;
}

export interface ManufactureItem {
  item_key: string;
  name: string;
  station: string;
  station_label: string;
  unlock_level: number;
  grade: number | null;
  category: string | null;
  sub_category: string | null;
  pic_url: string | null;
  period_hours: number | null;
  market_price: number | null;
  fee: number | null;
  profit: number | null;
  profit_per_hour: number | null;
  origin: string;
  fetched_at: string | null;
}

export interface ManufactureStationGroup {
  station: string;
  label: string;
  station_id: number;
  total: number;
  items: ManufactureItem[];
}

export interface ManufactureGroupedResponse {
  groups: ManufactureStationGroup[];
  levels: number[];
  origin: string;
  source: string;
  sort: string;
  order: string;
  per_station: number;
  fetched_at: string | null;
}

export interface ManufactureListResponse {
  items: ManufactureItem[];
  total: number;
  limit: number;
  offset: number;
  stations: ManufactureStation[];
  levels: number[];
  origin: string;
  source: string;
  fetched_at: string | null;
}

export interface ManufactureQuery {
  station?: string;
  level?: number;
  origin?: string;
  source?: string;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
  per_station?: number;
}

export interface ManufactureSyncResult {
  rows: number;
  requests: number;
  station_levels: number;
  errors: string[];
  started_at: string | null;
  finished_at: string | null;
}
