import type {
  DashboardSummary,
  Health,
  HistoryPeriod,
  ItemHistoryResponse,
  ItemListResponse,
  ItemQuery,
  ManufactureGroupedResponse,
  ManufactureQuery,
  ManufactureSyncResult,
} from "./types";

// 开发环境走 vite 代理（同源）；生产环境可用 VITE_API_BASE 指向后端
const BASE_URL = import.meta.env.VITE_API_BASE ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`请求失败 ${response.status} ${path}${body ? ` — ${body.slice(0, 200)}` : ""}`);
  }
  return (await response.json()) as T;
}

function toQueryString(query: ItemQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  return params.toString();
}

async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { method: "POST" });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`请求失败 ${response.status} ${path}${body ? ` — ${body.slice(0, 200)}` : ""}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => getJson<Health>("/health"),
  summary: () => getJson<DashboardSummary>("/api/dashboard/summary"),
  items: (query: ItemQuery) => getJson<ItemListResponse>(`/api/items?${toQueryString(query)}`),
  history: (itemId: string, period: HistoryPeriod) =>
    getJson<ItemHistoryResponse>(
      `/api/items/${encodeURIComponent(itemId)}/history?period=${period}`,
    ),
  manufacture: (query: ManufactureQuery) =>
    getJson<ManufactureGroupedResponse>(
      `/api/manufacture?${toQueryString(query as ItemQuery)}`,
    ),
  manufactureByStation: (query: ManufactureQuery) =>
    getJson<ManufactureGroupedResponse>(
      `/api/manufacture/by-station?${toQueryString(query as ItemQuery)}`,
    ),
  manufactureSync: () => postJson<ManufactureSyncResult>("/api/manufacture/sync"),
};
