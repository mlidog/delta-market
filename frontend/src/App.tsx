import { useCallback, useEffect, useState } from "react";

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
import StationPanel from "./components/StationPanel";
import SummaryCards, { statusLabel } from "./components/SummaryCards";
import {
  CATEGORY_OPTIONS,
  CHANGE_SORT_VALUES,
  MANUFACTURE_STATIONS,
  PAGE_SIZES,
  SORT_OPTIONS,
  categoryQuery,
} from "./constants";
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
  const [keyword, setKeyword] = useState(""); // 输入框里的原始内容
  const [search, setSearch] = useState(""); // 防抖之后真正发给接口的搜索词

  const [selected, setSelected] = useState<ItemPrice | null>(null);
  const [period, setPeriod] = useState<HistoryPeriod>("7d");
  const [history, setHistory] = useState<ItemHistoryResponse | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // ---- 制造排行 ----
  const [mfgSort, setMfgSort] = useState<"profit" | "profit_per_hour">("profit_per_hour");
  const [mfgLevel, setMfgLevel] = useState("");
  const [mfgNotice, setMfgNotice] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  // 变化时让四个站点面板重新拉数据
  const [refreshToken, setRefreshToken] = useState(0);

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
        search: search || undefined,
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
  }, [category, search, sort, order, limit, page]);

  useEffect(() => {
    void refreshOverview();
  }, [refreshOverview]);

  // 搜索走服务端（覆盖全部物品）。停顿 300ms 再发请求，避免每敲一个字打一次接口。
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(keyword.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [keyword]);

  useEffect(() => {
    if (tab === "items") void refreshItems();
  }, [tab, refreshItems]);

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
      setRefreshToken((token) => token + 1);
    } catch (error) {
      setMfgNotice(error instanceof Error ? `同步失败：${error.message}` : "同步失败");
    } finally {
      setSyncing(false);
    }
  }, []);

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
              else setRefreshToken((token) => token + 1);
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
                    placeholder="按名称搜索全部物品"
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

            {CHANGE_SORT_VALUES.has(sort) && (
              <div className="hint">
                涨幅排行中收集品与钥匙卡排在最后；想单独看它们，把「分类」切换成收集品或钥匙卡。
              </div>
            )}

            <ItemTable
              items={items}
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
            </h2>
            <div className="filters">
              <label>
                等级
                <select value={mfgLevel} onChange={(event) => setMfgLevel(event.target.value)}>
                  <option value="">全部等级</option>
                  {[1, 2, 3].map((level) => (
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

          {MANUFACTURE_STATIONS.map((station) => (
            <StationPanel
              key={station.key}
              stationKey={station.key}
              stationLabel={station.label}
              level={mfgLevel}
              sort={mfgSort}
              refreshToken={refreshToken}
            />
          ))}

          <div className="pager">
            <span className="muted">
              总收益 = 一轮制造的净收益；每小时收益 = 净收益 ÷ 制造时长；
              同一产物只显示已解锁的最高等级
            </span>
          </div>
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
