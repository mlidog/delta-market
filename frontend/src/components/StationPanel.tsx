import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { ManufactureItem } from "../api/types";
import { MANUFACTURE_PAGE_SIZE } from "../constants";
import ManufactureTable from "./ManufactureTable";

interface Props {
  /** 站点标识，如 tech / workbench */
  stationKey: string;
  stationLabel: string;
  /** 部门等级，空字符串表示全部等级 */
  level: string;
  sort: "profit" | "profit_per_hour";
  /** 变化时强制重新拉取（同步完成后用） */
  refreshToken: number;
}

export default function StationPanel({
  stationKey,
  stationLabel,
  level,
  sort,
  refreshToken,
}: Props) {
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<ManufactureItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 筛选条件变了就回到第一页
  useEffect(() => {
    setPage(1);
  }, [level, sort, refreshToken]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.manufacture({
        station: stationKey,
        level: level === "" ? undefined : Number(level),
        sort,
        order: "desc",
        limit: MANUFACTURE_PAGE_SIZE,
        offset: (page - 1) * MANUFACTURE_PAGE_SIZE,
      });
      setItems(response.items);
      setTotal(response.total);
      setError(null);
    } catch (caught) {
      setItems([]);
      setTotal(0);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [stationKey, level, sort, page]);

  useEffect(() => {
    void load();
  }, [load]);

  const pageCount = Math.max(1, Math.ceil(total / MANUFACTURE_PAGE_SIZE));

  return (
    <div className="station-group">
      <div className="station-head">
        <h3>{stationLabel}</h3>
        <div className="station-pager">
          <span className="muted">
            共 {total} 条 · 第 {page} / {pageCount} 页
          </span>
          <button
            className="ghost"
            disabled={page <= 1 || loading}
            onClick={() => setPage((current) => current - 1)}
          >
            上一页
          </button>
          <button
            className="ghost"
            disabled={page >= pageCount || loading}
            onClick={() => setPage((current) => current + 1)}
          >
            下一页
          </button>
        </div>
      </div>

      {error !== null && <div className="alert">接口报错：{error}</div>}

      <ManufactureTable items={items} loading={loading} rankBy={sort} />
    </div>
  );
}
