import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "./api/client";
import type {
  DashboardSummary,
  Health,
  HistoryPeriod,
  ItemHistoryResponse,
  ItemPrice,
} from "./api/types";
import ItemTable from "./components/ItemTable";
import PriceChart from "./components/PriceChart";
import SummaryCards, { statusLabel } from "./components/SummaryCards";
import { CATEGORY_OPTIONS, PAGE_SIZES, SORT_OPTIONS } from "./constants";
import { changeClass, formatClock, formatDateTime, formatNumber, formatPercent } from "./utils/format";

const PERIODS: HistoryPeriod[] = ["1h", "24h", "7d", "30d"];

export default function App() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [items, setItems] = useState<ItemPrice[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("bl_today");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [limit, setLimit] = useState(50);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");

  const [selected, setSelected] = useState<ItemPrice | null>(null);
  const [period, setPeriod] = useState<HistoryPeriod>("7d");
  const [history, setHistory] = useState<ItemHistoryResponse | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const refreshOverview = useCallback(async () => {
    const [nextSummary, nextHealth] = await Promise.all([
      api.summary().catch(() => null),
      api.health().catch(() => null),
    ]);
    setSummary(nextSummary);
    setHealth(nextHealth);
  }, []);

  const refreshItems = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.items({
        category: category || undefined,
        sort,
        order,
        limit,
        offset: (page - 1) * limit,
      });
      setItems(response.items);
      setTotal(response.total);
      setListError(null);
    } catch (error) {
      setItems([]);
      setTotal(0);
      setListError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, [category, sort, order, limit, page]);

  useEffect(() => {
    void refreshOverview();
  }, [refreshOverview]);

  useEffect(() => {
    void refreshItems();
  }, [refreshItems]);

  useEffect(() => {
    if (selected === null) {
      setHistory(null);
      return;
    }
    let cancelled = false;
    setHistoryError(null);
    api
      .history(selected.item_id, period)
      .then((response) => {
        if (!cancelled) setHistory(response);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setHistory(null);
          setHistoryError(error instanceof Error ? error.message : String(error));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected, period]);

  const visibleItems = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    if (needle === "") return items;
    return items.filter((item) => item.name.toLowerCase().includes(needle));
  }, [items, keyword]);

  const pageCount = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>三角洲物价观察</h1>
          <div className="topbar-sub">
            数据源 {health?.data_source ?? "—"} · 数据库 {health?.database ?? "—"}
            {health?.next_collect_at ? ` · 下次采集 ${formatClock(health.next_collect_at)}` : ""}
          </div>
        </div>
        <button
          className="ghost"
          onClick={() => {
            void refreshOverview();
            void refreshItems();
          }}
        >
          刷新
        </button>
      </header>

      <SummaryCards summary={summary} loading={loading} />

      <section className="panel">
        <div className="panel-head">
          <h2>物品行情</h2>
          <div className="filters">
            <label>
              搜索
              <input
                value={keyword}
                placeholder="按名称过滤当前页"
                onChange={(event) => setKeyword(event.target.value)}
              />
            </label>
            <label>
              分类
              <select
                value={category}
                onChange={(event) => {
                  setCategory(event.target.value);
                  setPage(1);
                }}
              >
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              排序
              <select value={sort} onChange={(event) => setSort(event.target.value)}>
                {SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              方向
              <select
                value={order}
                onChange={(event) => setOrder(event.target.value === "asc" ? "asc" : "desc")}
              >
                <option value="desc">从大到小</option>
                <option value="asc">从小到大</option>
              </select>
            </label>
            <label>
              每页
              <select
                value={limit}
                onChange={(event) => {
                  setLimit(Number(event.target.value));
                  setPage(1);
                }}
              >
                {PAGE_SIZES.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {listError !== null && <div className="alert">接口报错：{listError}</div>}

        <ItemTable
          items={visibleItems}
          selectedId={selected?.item_id ?? null}
          onSelect={(item) => {
            setSelected(item);
            setPeriod("7d");
          }}
          loading={loading}
        />

        <div className="pager">
          <span>
            共 {total} 个物品 · 第 {page} / {pageCount} 页
          </span>
          <div className="pager-buttons">
            <button className="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              上一页
            </button>
            <button
              className="ghost"
              disabled={page >= pageCount}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </button>
          </div>
        </div>
      </section>

      {selected !== null && (
        <section className="panel">
          <div className="panel-head">
            <h2>
              历史价格 · {selected.name}
              <span className="item-id"> {selected.item_id}</span>
            </h2>
            <div className="periods">
              {PERIODS.map((option) => (
                <button
                  key={option}
                  className={option === period ? "chip chip-active" : "chip"}
                  onClick={() => setPeriod(option)}
                >
                  {option}
                </button>
              ))}
              <button className="chip" onClick={() => setSelected(null)}>
                关闭
              </button>
            </div>
          </div>

          <div className="history-meta">
            <span>
              当前价 <b>{formatNumber(selected.price)}</b>
            </span>
            <span className={changeClass(selected.bl_today)}>
              今日 {formatPercent(selected.bl_today)}
            </span>
            <span className={changeClass(history?.change_pct ?? null)}>
              区间 {formatPercent(history?.change_pct ?? null)}
            </span>
            <span className="muted">
              {history ? `${history.point_count} 个快照` : "—"} · 最近更新{" "}
              {formatDateTime(selected.updated_at)}
            </span>
            {selected.is_stale && <span className="tag tag-stale">旧价</span>}
          </div>

          <PriceChart history={history} loading={loading} error={historyError} />
        </section>
      )}

      <footer className="footer">
        {health !== null && (
          <span>
            {health.app} v{health.version} · 调度器 {health.scheduler_running ? "运行中" : "已停止"}{" "}
            · 最近采集 {statusLabel(summary?.last_collect?.status ?? "unknown")}
          </span>
        )}
      </footer>
    </div>
  );
}
