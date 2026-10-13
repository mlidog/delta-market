import { useCallback, useEffect, useRef, useState } from "react";

import { IS_STATIC, api } from "./api";
import type {
  DashboardSummary,
  Health,
  HistoryPeriod,
  ItemPrice,
} from "./api/types";
import ItemTable from "./components/ItemTable";
import PriceBoard, { type BoardData } from "./components/PriceBoard";
import StationPanel from "./components/StationPanel";
import ChartPanel from "./components/ChartPanel";
import SummaryCards, { statusLabel, type MoverGroup } from "./components/SummaryCards";
import {
  CATEGORY_OPTIONS,
  CHANGE_SORT_VALUES,
  MANUFACTURE_STATIONS,
  MOVER_CATEGORIES,
  MOVER_LIMIT,
  PAGE_SIZES,
  SORT_OPTIONS,
  categoryQuery,
} from "./constants";
import { formatClock, formatDateTime } from "./utils/format";

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
  const [period, setPeriod] = useState<HistoryPeriod>("24h");
  // 三个分类的"今日变动最大"（顶部卡片用）
  const [movers, setMovers] = useState<MoverGroup[]>([]);

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

  /**
   * 顶部三张卡片：防护道具 / 枪械 / 子弹 里"今日价差"最大的若干个。
   *
   * 价差 = |当前价 − 今日开盘价|，看的是数值差距而不是百分比——
   * 十几块的子弹涨 30% 也比不上配件涨 3 万。后端 `price_delta` 就是这个值。
   */
  const loadMovers = useCallback(async () => {
    try {
      const groups = await Promise.all(
        MOVER_CATEGORIES.map(async (category) => {
          const response = await api.items({
            category: category.key,
            limit: MOVER_LIMIT,
            sort: "price_delta",
            order: "desc",
          });
          return {
            key: category.key,
            label: category.label,
            items: response.items.filter((item) => item.price_delta !== null),
          };
        }),
      );
      setMovers(groups);
    } catch {
      setMovers([]);
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

  const pendingScrollRef = useRef<string | null>(null);

  /**
   * 顶部卡片里点某个物品：它可能不在当前页/当前筛选里，
   * 所以先用精确名称过滤把它带进表格，再滚到那一行并展开曲线。
   */
  const handleMoverPick = useCallback((item: ItemPrice) => {
    setKeyword(item.name);
    setSearch(item.name);
    setPage(1);
    setSelected(item);
    setPeriod("7d");
    pendingScrollRef.current = item.item_id;
  }, []);

  // 等表格真的渲染出那一行再滚动，否则元素还不存在
  useEffect(() => {
    const pending = pendingScrollRef.current;
    if (pending === null) return;
    const row = document.getElementById(`item-row-${pending}`);
    if (row !== null) {
      pendingScrollRef.current = null;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    // 同名物品太多等原因导致一直找不到时不要无限等，4 秒后放弃，免得之后乱滚
    const timer = window.setTimeout(() => {
      pendingScrollRef.current = null;
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [items]);

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
    void loadMovers();
  }, [tab, refreshItems, loadBoard, loadMovers]);

  const pageCount = Math.max(1, Math.ceil(total / limit));
  // 右侧主图：点了物品就显示它，否则默认显示今日涨幅榜首（面板始终有内容）
  const primaryItem = selected ?? board?.gainers[0] ?? null;

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

      <SummaryCards
        summary={summary}
        loading={loading}
        movers={movers}
        onPick={handleMoverPick}
      />

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

          <div className={`items-layout${primaryItem !== null ? " with-chart" : ""}`}>
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

          {primaryItem !== null && (
            <ChartPanel
              primary={primaryItem}
              primaryLabel={selected !== null ? "你选中的物品" : "今日涨幅榜首"}
              secondary={selected === null ? (board?.losers[0] ?? null) : null}
              period={period}
              onPeriodChange={setPeriod}
            />
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
