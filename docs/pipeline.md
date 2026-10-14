# 从抓取到静态网站：完整流程

## 一、发布路径

| 路径 | 触发方式 | 数据新鲜度 | 前提 |
| --- | --- | --- | --- |
| **本机** | 本机后端每天 0/16/22 点调度 | 准时 | 本机能访问 GitHub |
| ~~GitHub Actions~~ | 已于 2026-10-14 移除 | — | — |

现在只有本机一条路径：本机后端每天 0/16/22 点采集 → 导出 JSON → 提交推送到 GitHub。

> **为什么移除 Actions**：GitHub 自己的 cron 不保证准时（实测晚 5~6.7 小时），
> 而且它每次触发都会真采一轮（32 次资源），和本机采集重复烧额度。
> 移除后线上 Pages 站点**不再自动重建**（部署也走这个 workflow），
> 需要恢复时：`git checkout 37457f3 -- .github/workflows/pages.yml`。

## 二、本机路径逐步拆解

### 第 0 步：定时触发（`app/scheduler.py`）

- APScheduler `BackgroundScheduler`，cron 表达式 `hour=0,16,22 minute=0`，时区 `Asia/Shanghai`
- 只注册**一个** job（id `collect-prices`），触发 `run_pipeline()`
  - 三步串在同一个 job 里是为了保证顺序：导出必须在采集与同步之后
- 启动补采**已关闭**（`COLLECTOR_RUN_ON_STARTUP=false`）：重启只加载代码，不采集
- 三个保护：`max_instances=1`（绝不并发）、`coalesce` + 1 小时宽限（休眠/重启错过时只补一次）、
  异常被吞掉只记日志（一次失败不影响后续轮次）
- ⚠️ 必须单 worker 运行 uvicorn，否则多个进程会各跑一套定时任务

### 第 1 步：采集全物品价格（`app/services/collector.py`）

1. 判断是否需要刷新物品目录：`COLLECTOR_ITEM_REFRESH_DAYS`（默认 7 天）内不重复拉
   → 需要时调 `item_info_all`（**20 次资源**）
2. 调 `item_price_all`（**20 次资源**），一次拿到全量 1360 个物品的价格
3. 落库三张表：
   - `items`：物品主数据（upsert）
   - `current_price`：每物品一行，覆盖更新；含平台自带的今日/3日/7日/30日涨跌幅、原始 JSON
   - `price_history`：追加一条快照（同一时刻重复采集幂等）
4. 重试策略：可重试错误（超时、连接失败、5xx、429）指数退避 1s / 4s / 16s，±30% 抖动，
   默认 3 次；不可重试错误（404 = Token 无效、业务错误码）立即失败
5. 失败处理：**不写入新数据**，把现存价格标记为 `stale` 并写 `collect_runs` 审计记录
6. 两条自愈规则：目录时间戳落在未来 → 强制刷新；价格批次里超过 10% 找不到对应物品
   → 立刻补一次目录再写价格（避免这一轮的 20 次资源白花）

### 第 2 步：同步特勤处制造收益（`app/services/manufacture.py`）

- 4 个站点 × 3 个部门等级 = **12 次请求 = 12 次资源**
- 每个（站点 × 等级）整段替换，不做历史累积（接口返回的就是"当前榜单"）
- 单个组合失败不影响其他组合，错误收进 `errors`

### 第 3 步：导出静态数据（`scripts/export_static.py`）

- **预热**：读 `frontend/public/data/items.json` 与 `history.json`，把物品目录和历史快照灌回数据库。
  云端（Actions）每次都是空库，不预热的话每轮都要多花 20 次资源重拉目录；本机已有数据则跳过
- **计算**：复用后端的涨跌幅逻辑（三组本地口径：较上次采集 / 较 24 小时前 / 较 7 天前）
- **写出 5 个 JSON**：

| 文件 | 内容 |
| --- | --- |
| `items.json` | 1360 条：名称、分类、等级、上次价、当前价、平台四组涨跌幅、本地三组涨跌幅、单格价值、采集时间 |
| `history.json` | 最近 30 天的快照点，按物品聚合（epoch 秒 + 价格） |
| `manufacture.json` | 441 条制造收益 |
| `summary.json` | 看板摘要 + 最近一次采集记录 |
| `meta.json` | 生成时间、条数、数据源、历史点数 |

> **关键设计：数据库是可丢弃的缓存，JSON 才是持久状态。**
> 云端不需要提交 SQLite 二进制文件；历史以文本形式增量提交，diff 也看得懂。

### 第 4 步：提交并推送（`app/services/publisher.py`）

1. `git add frontend/public/data` → 没有变化就跳过（不产生空提交）
2. `git commit -m "chore: 更新数据快照 [skip ci]"`
3. `git push origin main`：**先直连**；失败则读系统代理（环境变量 → 注册表 `ProxyEnable`/`ProxyServer`）
   用 `-c http.proxy=...` 重试
4. 推送失败不影响采集：本地提交保留，**下一次成功推送时会一并带上**（自愈）

> 为什么需要代理这一步：国内直连 `github.com:443` 经常不通，而 **git 默认不使用 Windows 系统代理**
> （只有浏览器 / .NET 会用），所以必须手动传给 git。

### 第 5 步：推送（原本由 Actions 构建部署，现已移除）

- 现在推送只把代码与 JSON 快照存到仓库，不再触发任何构建
- 线上 Pages 站点保持在最后一次部署的版本，本机更新不会反映到线上
- 前端静态版想本地看：`cd frontend; $env:VITE_STATIC="true"; npm run build; npm run preview`

## 三、GitHub Actions 路径（已移除）

保留这段说明是为了以后想恢复时知道它原来是怎么跑的：

- `on: schedule: cron "0 8,14,16 * * *"`（UTC）＝ 北京时间 16:00 / 22:00 / 次日 00:00
- 只有 `schedule` 与 `workflow_dispatch` 事件才执行"采集并导出"（32 次资源），
  然后构建、部署，最后把 JSON 提交回仓库
- Token 用仓库 Secret `DELTA_API_TOKEN`，**不读本机的 .env**
- ⚠️ 它不保证准时：实测晚 4 小时 55 分（本该 10-14 00:00 跑的那档，20:55 UTC 才启动）、
  甚至 20 小时只交付 1 次且晚 6 小时 40 分。这正是移除它的原因。

## 四、前端两种运行模式

| 模式 | 构建参数 | 数据来源 | 用途 |
| --- | --- | --- | --- |
| 本地 | 无 | 直连 FastAPI（`/api/*`） | 开发、实时查看 |
| 静态 | `VITE_STATIC=true` | 读 `data/*.json` | GitHub Pages |

- 切换点在 `frontend/src/api/index.ts`：`IS_STATIC ? staticApi : liveApi`
- 静态模式在浏览器里**复刻了后端的查询规则**：空值排最后、涨幅榜降权收集品与钥匙卡、
  制造榜同物品只留最高等级、分页
- ⚠️ 组件必须从 `../api` 引入 `api`。直接引 `../api/client` 会让静态站去请求不存在的 `/api/...`
  —— 这个错误本地看不出来，所以加了构建期检查脚本拦截（`frontend/scripts/check-api-imports.mjs`）

## 五、故障对照表

| 故障 | 表现 | 处理 |
| --- | --- | --- |
| Token 失效 | 采集 `failed`，价格全部标记旧价 | 更新 `.env` 的 `DELTA_API_TOKEN` 后重启后端 |
| 取价偶发失败 | 单轮失败，价格标 stale | 自动重试 3 次；下一次成功后自动清除标记 |
| 目录与价格不匹配 | 大量价格被跳过 | 自动补一次目录再写 |
| 推送失败（代理没开/断网） | 本地提交堆积，站点停止更新 | 恢复网络后下一次运行自动带上未推送的提交 |
| 线上站点不更新 | 数据/前端停在最后一次部署 | 部署用的 Actions workflow 已移除；需要时从 git 历史恢复后重新部署 |
| 前端误引实时客户端 | 静态站整块空白 | 构建期检查已拦截 |

## 六、每日资源消耗

| 调用 | 频次 | 单次 | 每天 |
| --- | --- | --- | --- |
| `item_price_all` | 3 次/天 | 20 | 60 |
| `item_info_all` | 每 7 天 1 次 | 20 | ≈ 3 |
| `manufacturePro` | 3 次/天 × 12 组合 | 1 | 36 |
| **合计** | | | **≈ 99 次/天** |

（Actions 那条路径移除后，这里是唯一的消耗来源；此前两边同时跑会让额度翻倍。）
