# 三角洲物价观察 — 实施计划（已确认版）

> 状态：M0 完成。本文件是团队和用户共同的唯一事实来源，计划变更时同步更新。

## 一、目标与范围

为《三角洲行动》玩家提供交易行物价观察工具。

MVP 内：定时采集全物品价格、物品列表（当前价 + 涨跌幅）、单物品历史曲线、基础筛选排序、看板摘要。

MVP 外（本阶段不做）：复杂预警规则引擎、用户系统与登录、正式生产部署、Docker 编排、前端看板（M7 单独启动）。

## 二、技术栈

- 后端：Python 3.11+（本机 3.12.5）、FastAPI、SQLAlchemy 2.x、SQLite、APScheduler 3.x、httpx、pydantic-settings
- 测试：pytest（+ pytest-asyncio）
- 前端：React + Vite + TypeScript + ECharts（M7，暂未开始）
- 部署：Docker Compose 暂不编写（本机也没有 Docker 环境）

## 三、目录结构

```
app/
  main.py              FastAPI 装配 + lifespan（启动/关闭调度器、建表）
  config.py            pydantic-settings 读取 .env
  database.py          engine / SessionLocal / Base / get_db
  models/              ORM：item.py、price.py、collect_run.py
  schemas/             Pydantic 出入参：item.py、price.py、dashboard.py
  api/deps.py          分页、DB 依赖
  api/routes/          health.py、items.py、dashboard.py
  services/            collector.py（采集编排）、pricing.py（涨跌幅与曲线聚合）
  data_sources/        base.py、mock.py、delta.py、registry.py —— 外部 HTTP 唯一出口
  scheduler.py         APScheduler 任务注册
tests/                 conftest.py、test_data_sources.py、test_collector.py、test_api.py
docs/                  plan.md、api_spec.md
```

依赖方向单向：`api → services → data_sources`，`models/schemas` 被各层共享但自身不依赖上层。

## 四、数据库 Schema（SQLite）

以「三角洲数据帝」的 **第三代数据 ID（oid / id）** 作为物品业务主键。

| 表 | 字段 | 说明 |
| --- | --- | --- |
| `items` | `item_id`(PK, TEXT)、`name`、`primary_class`、`second_class`、`second_class_cn`、`grade`、`pic_url`、`is_tradable`、`desc`、`official_object_id`、`legacy_id`、`created_at`、`updated_at` | 物品主数据 |
| `current_price` | `item_id`(PK, FK)、`price`、`price_start`、`day_3_price`、`day_7_price`、`day_30_price`、`source`、`updated_at`、`is_stale`、`last_error`、`consecutive_failures` | 每物品一行，采集后覆盖更新 |
| `price_history` | `id`(PK)、`item_id`(FK)、`price`、`source`、`recorded_at`，`(item_id, recorded_at)` 唯一索引 | 追加式时间序列快照 |
| `collect_runs` | `id`(PK)、`source`、`started_at`、`finished_at`、`status`、`items_ok`、`items_failed`、`error` | 每次采集的审计记录，用于标注"本次采集失败" |

关于买价/卖价：真实接口目前只返回单一价格字段 `price`，详见 `api_spec.md` 的待确认项。表结构将 `price` 作为规范价格字段，并预留 `buy_price`、`sell_price` 两列（可空），待口径确认后启用。

## 五、涨跌幅口径（三组）

所有涨跌幅在查询时计算，不写死在库里，便于口径调整与历史回填：

| 字段 | 口径 | 说明 |
| --- | --- | --- |
| `change_prev_pct` | 与上一次采集相比 | 取该物品倒数第二条快照 |
| `change_24h_pct` | 与 24 小时前相比 | 取距今 24h 最接近的快照；不足则返回 null |
| `change_7d_pct` | 与 7 天前相比 | 取距今 7d 最接近的快照；不足则返回 null |

数据不足时返回 `null` 而非 0，避免前端把"没有数据"显示成"没有变化"。

## 六、API 设计

| 方法 | 路径 | 参数 | 返回 |
| --- | --- | --- | --- |
| GET | `/health` | 无 | `status`、`database`、`data_source`、`scheduler_running`、`version` |
| GET | `/api/items` | `category`、`sort`(name/price/change_prev_pct/change_24h_pct/change_7d_pct)、`order`、`limit`(默认 50 上限 200)、`offset` | `{items, total, limit, offset}` |
| GET | `/api/items/{item_id}/history` | `period`=1h/24h/7d/30d | `{item_id, period, points:[{t, price}], change_pct}` |
| GET | `/api/dashboard/summary` | 无 | 物品总数、上涨/下跌/持平数、最近采集时间与状态、数据源 |

响应风格：HTTP 状态码 + 裸 JSON 对象，错误用 FastAPI 默认 `{detail: ...}`。 `/api/items` 的 `sort` 允许 `change_24h_pct` 等派生字段，排序在内存中完成（MVP 规模足够）。

## 七、采集与容错策略

**调度**：APScheduler `BackgroundScheduler` + `CronTrigger`，时区 `Asia/Shanghai`，每日 `0/8/18/22` 点各一次；`COLLECTOR_RUN_ON_STARTUP=true` 时应用启动后补采一次。调度器只在单进程内运行（多 worker 会重复触发，MVP 用单 worker，README 中注明）。

**重试**：`tenacity` 指数退避 + 抖动，最多 3 次尝试（间隔约 1s / 4s / 16s，±30% 抖动）。

- 重试：网络超时、连接错误、HTTP 5xx、HTTP 429（若响应带 `Retry-After` 则尊重该值）
- 不重试：401/403/404（Token 或权限问题，重试无意义，立即失败并记录明确错误）

**失败隔离**：以物品为粒度写入，单个物品异常不影响其他物品；数据源整体失败时**不写入新快照**，保留上一次价格，并在 `current_price` 上标记 `is_stale=1` + `last_error` + `consecutive_failures` 递增，同时在 `collect_runs` 写一条失败记录。恢复成功后清零这些标记。

**资源次数**：数据帝按"资源次数"计费，`item_price_all` 单次约 20 次资源、价格曲线单次 1 次。按每日 4 次全量采集估算约 80 次/天，需在文档中提醒用户。

## 八、里程碑

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M0 | 仓库初始化、依赖、测试框架 | 完成 |
| M1 | 配置、数据库、ORM 模型 | 待开始 |
| M2 | 数据源抽象层 + MockDataSource + api_spec.md | 待开始 |
| M3 | 采集服务（写入快照、失败标记） | 待开始 |
| M4 | 四个 API 接口 | 待开始 |
| M5 | 定时任务 | 待开始 |
| M6 | DeltaDataSource（真实数据帝 API） | 待开始 |
| M7 | 前端看板 | 待开始 |
