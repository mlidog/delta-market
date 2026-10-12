import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "./api/client";
import type {
  DashboardSummary,
  Health,
  HistoryPeriod,
  ItemHistoryResponse,
  ItemPrice,
  ManufactureGroupedResponse,
} from "./api/types";
import ItemTable from "./components/ItemTable";
import ManufactureTable from "./components/ManufactureTable";
import PriceChart from "./components/PriceChart";
import SummaryCards, { statusLabel } from "./components/SummaryCards";
import { CATEGORY_OPTIONS, PAGE_SIZES, SORT_OPTIONS, categoryQuery } from "./constants";
import {
  changeClass,
  formatClock,
  formatDateTime,
  formatNumber,
  formatPercent,
} from "./utils/format";

const PERIODS: HistoryPeriod[] = ["1h", "24h", "7d", "30d"];
type Tab = "items" | "manufacture";

export default function App() {
  const [tab, setTab] = useState<Tab>("items");

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);

  // ---- 物品行情 ----
  const [items, setItems] = useState<ItemPrice[]>([]);
  const [total, setTotal] = useState(0);
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

  // ---- 制造排行 ----
  const [mfgSort, setMfgSort] = useState<"profit" | "profit_per_hour">("profit_per_hour");
  const [mfgLevel, setMfgLevel] = useState("");
  const [mfg, setMfg] = useState<ManufactureGroupedResponse | null>(null);
  const [mfgLoading, setMfgLoading] = useState(false);
  const [mfgError, setMfgError] = useState<string | null>(null);
  const [mfgNotice, setMfgNotice] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

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
        ...categoryQuery(category),
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

  const refreshManufacture = useCallback(async () => {
    setMfgLoading(true);
    try {
      // 按站点分组：四个站点各出一张榜，站内按选定依据排序
      const response = await api.manufactureByStation({
        level: mfgLevel === "" ? undefined : Number(mfgLevel),
        sort: mfgSort,
        order: "desc",
        per_station: 20,
      });
      setMfg(response);
      setMfgError(null);
    } catch (error) {
      setMfg(null);
      setMfgError(error instanceof Error ? error.message : String(error));
    } finally {
      setMfgLoading(false);
    }
  }, [mfgLevel, mfgSort]);

  useEffect(() => {
    void refreshOverview();
  }, [refreshOverview]);

  useEffect(() => {
    if (tab === "items") void refreshItems();
  }, [tab, refreshItems]);

  useEffect(() => {
    if (tab === "manufacture") void refreshManufacture();
  }, [tab, refreshManufacture]);

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

  const runSync = useCallback(async () => {
    const confirmed = window.confirm(
      "这会真实消耗平台资源：每个（站点 × 等级）计 1 次，完整同步约 12 次。确定继续？",
    );
    if (!confirmed) return;
    setSyncing(true);
    setMfgNotice(null);
    try {
      const result = await api.manufactureSync();
      setMfgNotice(
        `同步完成：写入 ${result.rows} 条，请求 ${result.requests} 次，成功组合 ${result.station_levels}` +
          (result.errors.length > 0 ? `，失败 ${result.errors.length} 个` : ""),
      );
      await refreshManufacture();
    } catch (error) {
      setMfgNotice(error instanceof Error ? `同步失败：${error.message}` : "同步失败");
    } finally {
      setSyncing(false);
    }
  }, [refreshManufacture]);

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
        <div className="topbar-actions">
          <div className="tabs">
            <button
              className={tab === "items" ? "chip chip-active" : "chip"}
              onClick={() => setTab("items")}
            >
              物品行情
            </button>
            <button
              className={tab === "manufacture" ? "chip chip-active" : "chip"}
              onClick={() => setTab("manufacture")}
            >
              制造排行
            </button>
          </div>
          <button
            className="ghost"
            onClick={() => {
              void refreshOverview();
              if (tab === "items") void refreshItems();
              else void refreshManufacture();
            }}
          >
            刷新
          </button>
        </div>
      </header>

      <SummaryCards summary={summary} loading={loading} />

      {tab === "items" && (
        <>
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
        </>
      )}

      {tab === "manufacture" && (
        <section className="panel">
          <div className="panel-head">
            <h2>
              特勤处制造收益
              {mfg?.fetched_at ? (
                <span className="item-id"> 数据抓取于 {formatDateTime(mfg.fetched_at)}</span>
              ) : null}
            </h2>
            <div className="filters">
              <label>
                等级
                <select value={mfgLevel} onChange={(event) => setMfgLevel(event.target.value)}>
                  <option value="">全部等级</option>
                  {(mfg?.levels ?? [1, 2, 3]).map((level) => (
                    <option key={level} value={level}>
                      {level} 级
                    </option>
                  ))}
                </select>
              </label>
              <label>
                排行依据
                <select
                  value={mfgSort}
                  onChange={(event) =>
                    setMfgSort(event.target.value === "profit" ? "profit" : "profit_per_hour")
                  }
                >
                  <option value="profit_per_hour">每小时收益（产线不停）</option>
                  <option value="profit">总收益（上线次数少）</option>
                </select>
              </label>
              <label>
                &nbsp;
                <button className="ghost" disabled={syncing} onClick={() => void runSync()}>
                  {syncing ? "同步中…" : "同步制造收益"}
                </button>
              </label>
            </div>
          </div>

          {mfgNotice !== null && <div className="alert">{mfgNotice}</div>}
          {mfgError !== null && <div className="alert">接口报错：{mfgError}</div>}

          {mfg?.groups.map((group) => (
            <div key={group.station} className="station-group">
              <div className="station-head">
                <h3>{group.label}</h3>
                <span className="muted">
                  共 {group.total} 条 · 展示前 {group.items.length} 条
                </span>
              </div>
              <ManufactureTable items={group.items} loading={mfgLoading} rankBy={mfgSort} />
            </div>
          ))}

          {mfg !== null && (
            <div className="pager">
              <span>
                共 {mfg.groups.reduce((sum, group) => sum + group.total, 0)} 条（数据来源{" "}
                {mfg.source} · 口径 {mfg.origin}）
              </span>
              <span className="muted">
                总收益 = 一轮制造的净收益；每小时收益 = 净收益 ÷ 制造时长
              </span>
            </div>
          )}
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
