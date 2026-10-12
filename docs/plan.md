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
| `items` | `item_id`(PK, TEXT)、`name`、`primary_class`、`second_class`、`second_class_cn`、`grade`、`pic_url`、`is_tradable`、`object_id`、`slot_w`、`slot_h`、`created_at`、`updated_at` | 物品主数据。`object_id` 为官方小程序 ID，`slot_w`/`slot_h` 用于计算单格价值 |
| `current_price` | `item_id`(PK, FK)、`price`、`price_start`、`bl_today`、`day_3_price`/`day_3_bl`、`day_7_price`/`day_7_bl`、`day_30_price`/`day_30_bl`、`source_updated_at`、`raw_json`、`source`、`updated_at`、`status`、`last_error`、`consecutive_failures` | 每物品一行，采集后覆盖更新。`raw_json` 保留接口原始记录，便于后续加功能时无需改表 |
| `price_history` | `id`(PK)、`item_id`(FK)、`price`、`source`、`recorded_at`，`(item_id, recorded_at)` 唯一索引 | 追加式时间序列快照 |
| `collect_runs` | `id`(PK)、`source`、`started_at`、`finished_at`、`status`、`items_ok`、`items_failed`、`error` | 每次采集的审计记录，用于标注"本次采集失败" |

关于买价/卖价：真实接口目前只返回单一价格字段 `price`，详见 `api_spec.md` 的待确认项。表结构将 `price` 作为规范价格字段，并预留 `buy_price`、`sell_price` 两列（可空），待口径确认后启用。

## 五、涨跌幅口径（三组）

### 5.1 自算口径（依赖本地历史快照）

| 字段 | 口径 | 说明 |
| --- | --- | --- |
| `change_prev_pct` | 与上一次采集相比 | 取该物品倒数第二条快照 |
| `change_24h_pct` | 与 24 小时前相比 | 取距今 24h 最接近的快照；不足则返回 null |
| `change_7d_pct` | 与 7 天前相比 | 取距今 7d 最接近的快照；不足则返回 null |

数据不足时返回 `null` 而非 0，避免前端把"没有数据"显示成"没有变化"。

### 5.2 平台口径（免费搭车，无需额外请求）

`item_price_all` 同一次请求就会返回平台算好的四个周期涨跌幅，直接入库并透传给前端：

| 字段 | 平台含义 |
| --- | --- |
| `bl_today` | 今日涨跌比例（相对今日最初价格 `price_start`） |
| `day_3_bl` / `day_7_bl` / `day_30_bl` | 3 日 / 7 日 / 30 日涨跌比例 |
| `price_start` | 今日最初价格（相当于今日开盘价） |

两套口径并存不是冗余：自算口径粒度更细、可覆盖任意时间窗；平台口径在本地历史不足时（例如刚上线第一天）
能立刻给出 3/7/30 日维度，避免前端空白。

## 六、API 设计

| 方法 | 路径 | 参数 | 返回 |
| --- | --- | --- | --- |
| GET | `/health` | 无 | `status`、`database`、`data_source`、`scheduler_running`、`version` |
| GET | `/api/items` | `category`、`sort`(name/price/change_prev_pct/change_24h_pct/change_7d_pct)、`order`、`limit`(默认 50 上限 200)、`offset` | `{items, total, limit, offset}` |
| GET | `/api/items/{item_id}/history` | `period`=1h/24h/7d/30d | `{item_id, period, points:[{t, price}], change_pct}` |
| GET | `/api/dashboard/summary` | 无 | 物品总数、上涨/下跌/持平数、最近采集时间与状态、数据源 |

响应风格：HTTP 状态码 + 裸 JSON 对象，错误用 FastAPI 默认 `{detail: ...}`。 `/api/items` 的 `sort` 允许 `change_24h_pct` 等派生字段，排序在内存中完成（MVP 规模足够）。

## 七、采集与容错策略

**调度**：APScheduler `BackgroundScheduler` + `CronTrigger`，时区 `Asia/Shanghai`，每日 `0/16/22` 点各一次（3 次/天）；`COLLECTOR_RUN_ON_STARTUP=true` 时应用启动后补采一次。调度器只在单进程内运行（多 worker 会重复触发，MVP 用单 worker，README 中注明）。

0 点这一次是有意保留的：游戏每日价格重置，0 点采样拿到的是「今日开盘价」，对涨跌分析价值最高。

**重试**：`tenacity` 指数退避 + 抖动，最多 3 次尝试（间隔约 1s / 4s / 16s，±30% 抖动）。

- 重试：网络超时、连接错误、HTTP 5xx、HTTP 429（若响应带 `Retry-After` 则尊重该值）
- 不重试：401/403/404（Token 或权限问题，重试无意义，立即失败并记录明确错误）

**失败隔离**：以物品为粒度写入，单个物品异常不影响其他物品；数据源整体失败时**不写入新快照**，保留上一次价格，并在 `current_price` 上标记 `is_stale=1` + `last_error` + `consecutive_failures` 递增，同时在 `collect_runs` 写一条失败记录。恢复成功后清零这些标记。

**资源次数**：数据帝按"资源次数"计费。2026-10-12 于控制台实测确认：`item_price_all` **扣 20 次**（3,000 → 2,980），
`day` 价格曲线 **扣 1 次**（2,980 → 2,979），与文档口径一致。

### 成本估算（2026-10-12 于控制台核实）

计费口径：**¥1 = 1 硬币**（充值档位 ¥5/¥10/¥20/¥199/自定义，无批量折扣）。
「三角洲数据帝 - 基础接口」只有两个套餐档位：

| 套餐 | 硬币 | 资源次数 | 单位资源成本 |
| --- | --- | --- | --- |
| 小包 | 20 | 3,000 | ¥0.0066667 |
| 大包 | 199 | 220,000 | ¥0.0009045 |

大包的单位成本是小包的 **1/7.37**，这是最重要的成本杠杆。

消耗量（每日 3 次采集，0/16/22 点）：

| 调用 | 频次 | 单次消耗 | 每日消耗 |
| --- | --- | --- | --- |
| `item_price_all`（全物品最新价格） | 3 次/天（0/16/22） | 20 资源 | 60 |
| `item_info_all`（全物品基础信息） | 启动 + 每周 1 次 | 20 资源 | ≈ 3 |
| 价格曲线 `minute`/`hour`/`day` | 不使用（用自建快照） | 1 资源 | 0 |
| 前端看板查询 | 本地 SQLite 查询 | 0 | 0 |
| **合计** | | | **≈ 63 资源/天 ≈ 1,915 资源/月** |

作为对照：官方文档示例中「20 分钟/次全量刷新」为 720 资源/天（约 21600 资源/月），本项目模型约为其 1/11。

据此得到的实际成本：

| 采集频次 | 资源/天 | 资源/月 | 小包成本/月 | 大包成本/月 |
| --- | --- | --- | --- | --- |
| **3 次/天（0/16/22）← 已选定** | ≈ 63 | ≈ 1,915 | ¥12.7 | **¥1.73** |
| 2 次/天（0/22） | ≈ 43 | ≈ 1,303 | ¥8.7 | ¥1.18 |
| 1 次/天（0 点） | ≈ 23 | ≈ 695 | ¥4.6 | ¥0.63 |

年化对比（3 次/天）：小包 ≈ ¥153/年，大包 ≈ ¥21/年。控制台当前剩余 2,979 次，按 3 次/天可用约 **47 天**。

成本控制要点：

1. **采购换档**：选 199 硬币大包，单位成本直接降到 1/7.37，收益远大于任何频次调整。
2. **失败请求不扣资源**（平台明示：异常或未正常返回数据不消耗资源），因此重试策略不会带来额外成本，可以放心保留指数退避重试。
3. **平台鼓励缓存**（原文：「为了确保您资源能更慢的消耗，您需要使您的网页具有 数据缓存 功能」），本项目自建的
   `current_price` + `price_history` 正是这层缓存。
4. 全量价格必须走 `item_price_all` 单次全量接口，**不要**用 `item_list` / `item_list_pro` 分页接口拼全量
   （每页仅 10~20 条，1,200+ 物品需要 60+ 次请求，比一次 20 资源更贵）。
5. `item_info_all` 用本地缓存，只在启动与每周一次刷新（约 2.9 资源/天）。
6. 历史曲线优先用自建 `price_history`，只有自身历史不足的时段才回落到曲线接口。
7. 频次取舍：平台接口自带 `bl` / `day_3_bl` / `day_7_bl` / `day_30_bl`，所以涨跌幅展示不依赖高频采集；
   但「与上一次采集相比」这组至少需要 2 次/天。建议保留 **0 点**（游戏每日价格重置，可捕获开盘价，
   对涨跌分析价值最高），中间时段可视需要裁掉。

## 八、里程碑

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M0 | 仓库初始化、依赖、测试框架 | 完成 |
| M1 | 配置、数据库、ORM 模型 | 完成 |
| M2 | 数据源抽象层 + MockDataSource + api_spec.md | 完成 |
| M3 | 采集服务（写入快照、失败标记） | 完成 |
| M4 | 四个 API 接口 | 待开始 |
| M5 | 定时任务 | 待开始 |
| M6 | DeltaDataSource（真实数据帝 API） | 待开始 |
| M7 | 前端看板 | 待开始 |

## 九、设计复查结论（2026-10-12）

### 9.1 需要清理的冗余

| 项 | 结论 |
| --- | --- |
| `items.legacy_id`（第二代 ID `tid`） | **删除**。官方已明确"目前已不适用，记录对照即可"，保留没有使用场景 |
| `current_price` 与 `price_history` 最新一行 | 保留。这是有意的反范式：列表页单表查询，且失败标记、`raw_json` 等状态字段只应存在于当前价表 |
| `price_start` vs `change_24h_pct` | 都保留。前者是"今日开盘价"，后者是"24 小时前"，语义不同 |

### 9.2 零额外 API 成本即可增加的功能

数据已经随 `item_price_all` / `item_info_all` 免费带回，只需入库并透传，不增加任何资源消耗：

1. **多周期涨跌幅**：`bl_today` / `day_3_bl` / `day_7_bl` / `day_30_bl`，前端可自由切换周期（平台自家页面就是这么做的）。
2. **单格价值**：`price ÷ (slot_w × slot_h)`，用基础信息里的宽高计算。平台有独立的"物品单格价值"工具，
   官方页面实测列表为「物品 / 单格价值 / 格数 / 当前价格」，说明这是玩家刚需，且可以直接做排序。
3. **数据新鲜度**：透传 `is_get_time`（价格更新时间戳），前端可显示"价格更新于 xx:xx"，也能识别平台自身的数据延迟。
4. **更细的筛选维度**：`primary_class`（一级）、`second_class_cn`（二级中文）、`grade`（等级）、`mtype`（收集品子类）。
   `/api/items` 由单一 `category` 扩展为 `category` + `sub_category` + `grade`。
5. **原始记录留档**：`current_price.raw_json` 存接口原始 JSON，后续平台加字段时无需改表结构。

### 9.3 需要额外请求、建议二期实现

| 功能 | 数据来源 | 成本 |
| --- | --- | --- |
| 30 天最高/最低价（"是否处于历史低位"，价格预警的基础） | `day` 曲线的 `max`/`maxD`/`min`/`minD` | 1 资源/物品/次，按需触发 |
| 未来价格预测 | `hour` 曲线（含未来价值预测） | 1 资源/物品/次 |
| 卖出建议（交易行上架 vs 秒出） | `ShopSellType`，仅 `item_list` / `item_list_pro` 返回 | 分页请求，建议只对用户查看的单个物品按需查询 |
| 卡战备 / 假账（`zb_price`/`zb_jz`/`zb_bl`） | `item_list?types=zhanbei` | 平台标注战备数据"暂不开放"，需先确认 |

### 9.4 本地计算即可实现（不消耗资源）

- **市场指数**：以首次采集为基期 1000，按分类做加权平均，输出总指数与各分类指数。
  平台有对应的"市场指数"页面（含今日/7 日/30 日涨跌、72 小时趋势、区间最高/最低），是很好的参考形态。
- **上涨/下跌家数、涨跌分布**：看板摘要的天然扩展。

### 9.5 明确排除

平台还提供今日密码、改枪码、制造利润、军需处兑换、钥匙卡/子弹预测等接口，均不属于本工具目标，
列入非目标，避免范围蔓延。
