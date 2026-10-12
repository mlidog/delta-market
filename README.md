# 三角洲物价观察

《三角洲行动》交易行物价观察工具。当前处于 **后端 MVP** 阶段。

## 里程碑进度

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M0 | 仓库初始化、依赖、测试框架 | 完成 |
| M1 | 配置、数据库、ORM 模型 | 完成 |
| M2 | 数据源抽象层 + MockDataSource | 完成 |
| M3 | 采集服务（写入价格快照） | 完成 |
| M4 | 四个 API 接口 | 完成 |
| M5 | 定时任务（每日 0/16/22 点） | 完成 |
| M6 | DeltaDataSource（真实数据帝 API） | 完成 |
| M7 | 前端看板 | 完成 |
| M8 | 特勤处制造收益排行 | 完成 |

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

Copy-Item .env.example .env

pytest
```

## 数据源

所有外部 HTTP 调用集中在 `app/data_sources/`。默认使用 `MockDataSource`，无需 Token 即可离线开发；
切换到真实数据源只需在 `.env` 中把 `DATA_SOURCE` 改为 `delta` 并填入 `DELTA_API_TOKEN`。

真实数据源接口文档与调研结果见 [`docs/api_spec.md`](docs/api_spec.md)，整体计划见 [`docs/plan.md`](docs/plan.md)。

## 注意事项

- 调度器运行在应用进程内，请使用**单 worker**启动 uvicorn，否则定时任务会被重复触发。
- 多进程部署时用 `SCHEDULER_ENABLED=false` 关掉除一个进程之外的所有调度器。
- 数据帝 API 按"资源次数"计费，全量价格接口单次约消耗 20 次资源。

## 定时采集

应用启动后会拉起调度器，按 `COLLECTOR_CRON_HOURS`（默认北京时间 0 / 16 / 22 点）自动采集。

- `COLLECTOR_RUN_ON_STARTUP=true` 时启动后会立刻补采一次，避免看板为空
- `SCHEDULER_ENABLED=false` 可整体关闭本进程的定时采集
- `/health` 的 `next_collect_at` 字段能看到下一次采集时间

调度器带两个保护：同一任务不并发执行（`max_instances=1`），系统休眠或重启错过触发时
只补跑一次而不是把错过的轮次全部堆着跑（`coalesce` + 1 小时宽限期）。

**成本保护**：`item_info_all` 与 `item_price_all` 各消耗 20 次资源，而物品的名称、分类、
占格几乎不变，所以基础信息默认按 `COLLECTOR_ITEM_REFRESH_DAYS`（7 天）缓存，
每轮只拉价格。此外还有两条自愈规则：

- 目录时间戳落在未来（导入过演示数据、改过系统时间）时强制刷新一次
- 价格批次里有 10% 以上找不到对应物品时（换了数据源、游戏新增物品），
  立刻补一次目录再写价格，避免这一轮的取价白花

## 启动与接口

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

交互式文档在 http://127.0.0.1:8000/docs

| 接口 | 说明 |
| --- | --- |
| `GET /health` | 健康检查：数据库、数据源、调度器状态 |
| `GET /api/items` | 物品列表，支持 `category` / `sub_category` / `grade` / `tradable` 筛选，`sort` / `order` / `limit` / `offset` 排序分页 |
| `GET /api/items/{item_id}/history` | 单物品历史曲线，`period` 支持 `1h` / `24h` / `7d` / `30d` |
| `GET /api/dashboard/summary` | 看板摘要：物品总数、涨跌家数、最近采集状态 |
| `GET /api/manufacture` | 特勤处制造收益排行（跨站点平铺），支持 `station` / `level` / `sort=profit\|profit_per_hour` |
| `GET /api/manufacture/by-station` | 同上，但**按站点分组**返回四个站点各自的榜（前端默认用这个） |
| `POST /api/manufacture/sync` | 立即同步制造收益（⚠️ 消耗平台资源，完整同步 12 次） |

`/api/items` 每项同时给出两套涨跌幅：平台口径（`bl_today` / `day_3_bl` / `day_7_bl` / `day_30_bl`）
与本地口径（`change_prev_pct` / `change_24h_pct` / `change_7d_pct`）。本地口径依赖自建历史快照，
数据不足时返回 `null`，不会退化成 0。

响应里的时间统一是带 `Z` 的 UTC ISO8601，前端按需转换成北京时间。

### 手动采集一次

```powershell
.\.venv\Scripts\python.exe -c "from app.services import Collector; print(Collector().run())"
```

### 真实数据源联调

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_delta
```

该脚本会完整同步一次制造收益（12 次资源）、用官方口径交叉校验字段含义，并打印两张排行榜。
必须用 `-m` 从项目根目录运行。

## 前端看板

前端在 `frontend/`，Vite + React + TypeScript + ECharts。

```powershell
cd frontend
npm install
npm run dev          # 打开 http://127.0.0.1:5173
```

开发服务器会把 `/api` 与 `/health` 代理到 `http://127.0.0.1:8000`（见 `frontend/vite.config.ts`），
所以要先启动后端。

看板包含三块：

1. **摘要卡片**：物品总数、今日上涨/下跌家数、最近一次采集状态（失败时会有黄色提示条）
2. **物品行情表**：支持分类筛选、11 种排序字段、翻页，以及"较上次采集 / 较 24 小时前 / 较 7 天前"
   三组本地口径涨跌幅；显示为 `—` 表示历史不足，不是零波动
3. **历史曲线**：点击任意行展开，支持 1h / 24h / 7d / 30d 切换

```powershell
npm run build        # 类型检查 + 生产构建（产物在 frontend/dist）
```
