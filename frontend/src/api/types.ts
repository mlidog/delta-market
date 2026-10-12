/** 与后端 `app/schemas` 一一对应的类型定义。 */

export type HistoryPeriod = "1h" | "24h" | "7d" | "30d";

export interface ItemPrice {
  item_id: string;
  name: string;
  category: string | null;
  sub_category: string | null;
  grade: number | null;
  pic_url: string | null;
  is_tradable: boolean;
  slot_w: number | null;
  slot_h: number | null;
  slot_area: number | null;
  price_per_slot: number | null;
  price: number | null;
  price_start: number | null;
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
  grade?: number;
  tradable?: boolean;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}
