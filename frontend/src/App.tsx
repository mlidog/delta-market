import { useCallback, useEffect, useState } from "react";

import { IS_STATIC, api } from "./api";
import type {
  DashboardSummary,
  Health,
  HistoryPeriod,
  ItemHistoryResponse,
  ItemPrice,
} from "./api/types";
import ItemTable from "./components/ItemTable";
import PriceChart from "./components/PriceChart";
import PriceBoard, { type BoardData } from "./components/PriceBoard";
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
  const [grade, setGrade] = useState("");
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

  // ---- 涨跌榜 ----
  const [board, setBoard] = useState<BoardData | null>(null);
  const [boardOpen, setBoardOpen] = useState(false);

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
        grade: grade === "" ? undefined : Number(grade),
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
  }, [category, grade, search, sort, order, limit, page]);

  /** 24 小时涨跌榜（各 10 件）。本地历史不足 24 小时时退回平台的"今日涨跌"。 */
  const loadBoard = useCallback(async () => {
    try {
      const [top, bottom] = await Promise.all([
        api.items({ sort: "change_24h_pct", order: "desc", limit: 10 }),
        api.items({ sort: "change_24h_pct", order: "asc", limit: 10 }),
      ]);
      if ((top.items[0]?.change_24h_pct ?? null) !== null) {
        setBoard({ metric: "change_24h_pct", gainers: top.items, losers: bottom.items });
        return;
      }
      const [gainers, losers] = await Promise.all([
        api.items({ sort: "bl_today", order: "desc", limit: 10 }),
        api.items({ sort: "bl_today", order: "asc", limit: 10 }),
      ]);
      setBoard({ metric: "bl_today", gainers: gainers.items, losers: losers.items });
    } catch {
      setBoard(null);
    }
  }, []);

  useEffect(() => {
    void refreshOverview();
  }, [refreshOverview]);

  /** 点条目选中并在右侧展开曲线；再点同一个则收起。 */
  const selectItem = useCallback((item: ItemPrice) => {
    setSelected((current) => (current?.item_id === item.item_id ? null : item));
    setPeriod("7d");
  }, []);

  // 搜索走服务端（覆盖全部物品）。停顿 300ms 再发请求，避免每敲一个字打一次接口。
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(keyword.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [keyword]);

  useEffect(() => {
    if (tab !== "items") return;
    void refreshItems();
    void loadBoard();
  }, [tab, refreshItems, loadBoard]);

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
        </div>
      </header>

      <SummaryCards summary={summary} loading={loading} />

      {tab === "items" && (
        <>
          {board !== null && (
            <PriceBoard
              board={board}
              open={boardOpen}
              onToggle={() => setBoardOpen((open) => !open)}
              onSelect={selectItem}
            />
          )}

          <div className={`items-layout${selected !== null ? " with-chart" : ""}`}>
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
                  等级
                  <select
                    value={grade}
                    onChange={(event) => {
                      setGrade(event.target.value);
                      setPage(1);
                    }}
                  >
                    <option value="">全部等级</option>
                    {[6, 5, 4, 3, 2, 1].map((value) => (
                      <option key={value} value={value}>
                        {value} 级
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
              onSelect={selectItem}
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
            <aside className="panel chart-column">
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
            </aside>
          )}
          </div>
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
                {IS_STATIC ? (
                  <>
                    &nbsp;
                    <span className="muted" style={{ fontSize: 12 }}>
                      静态版：数据由 GitHub Actions 定时更新
                    </span>
                  </>
                ) : (
                  <>
                    &nbsp;
                    <button className="ghost" disabled={syncing} onClick={() => void runSync()}>
                      {syncing ? "同步中…" : "同步制造收益"}
                    </button>
                  </>
                )}
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
            {health.app} v{health.version} ·{" "}
            {IS_STATIC
              ? `静态数据快照（${formatDateTime(summary?.generated_at)} 生成）`
              : `调度器 ${health.scheduler_running ? "运行中" : "已停止"}`}{" "}
            · 最近采集 {statusLabel(summary?.last_collect?.status ?? "unknown")}
          </span>
        )}
      </footer>
    </div>
  );
}
