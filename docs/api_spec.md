# 三角洲数据帝 API 规格（调研结果）

> 本文件由公开资料调研得出，**尚未用真实 Token 验证**。M6 接入真实接口时逐条核对并更新。

## 一、来源

| 项 | 值 |
| --- | --- |
| 官方开放平台（申请 Token） | https://orzice.com/work/ |
| API 文档（Apifox） | https://work-api.apifox.cn |
| 官方 SDK 仓库 | https://github.com/orzice/DeltaForceApi |
| 交流 QQ 群 | 791785919 |

## 二、通用约定

| 项 | 值 |
| --- | --- |
| Base URL | `https://orzice.com/workApi` |
| 鉴权 | 查询参数 `token=<DELTA_API_TOKEN>` |
| User-Agent | `DeltaForceApi/1.0` |
| 响应信封 | `{"code": 0, "msg": "成功", "count": N, "data": ...}`，`code != 0` 视为业务失败 |
| 无权限 | HTTP 404（文档原话：请检查 token 是否正确） |
| 计费 | 按"资源次数"扣减：`item_info_all` 约 20 次，`item_price_all` 约 20 次，价格曲线 1 次 |

## 三、MVP 需要的接口

### 3.1 全物品基础信息库

`GET /v1/sjz_api/item_info_all`

| 字段 | 含义 |
| --- | --- |
| `oid` | **第三代数据 ID**（其他接口用它），不可交易时为 0 |
| `id` | 第二代数据 ID（已不适用，仅对照） |
| `objectID` | 三角洲官方小程序 ID |
| `objectName` | 物品名称 |
| `primaryClass` / `secondClass` / `secondClassCN` | 一/二/三级分类（如 `ammo` / `6.8x51mm` / `ammo6.8x51`） |
| `grade` | 等级（0~6） |
| `is_get` | 是否可在交易行交易，0=不可交易 1=可交易 |
| `pic` | 图片 URL |
| `width` / `length` | 占格宽高 |
| `desc` / `detail` | 文本介绍 / 扩展参数（detail 为 JSON 字符串） |

### 3.2 全物品最新价格

`GET /v1/sjz_api/item_price_all?isZb=0`

| 字段 | 含义 |
| --- | --- |
| `id` | **第三代数据 ID**（对应 3.1 的 `oid`） |
| `tid` | 第二代数据 ID |
| `price` | 当前价格 |
| `price_start` | 今日最初价格 |
| `bl` | 今日涨跌比例 |
| `day_3_price` / `day_3_bl` | 3 日价格 / 涨跌幅 |
| `day_7_price` / `day_7_bl` | 7 日价格 / 涨跌幅 |
| `day_30_price` / `day_30_bl` | 30 日价格 / 涨跌幅 |
| `is_get_time` | 价格更新时间戳 |
| `zb_price` | 战备值（每周二 10:00 前人工更新） |

> `isZb=1`（战备数据）文档标注为【暂不开放】。

### 3.3 全物品列表 / Top 排行（分页）

`GET /v1/sjz_api/item_list?lx=list&p=1&limit=10&types=acc&top=1-1`

- `lx`：`list` 列表 / `top` 排行
- `p`：页码；`limit`：每页 10~20
- `types`：`zhanbei`、`acc`、`ammo`、`gun`、`collection`、`consume`、`helmet`、`armor`、`bag`、`chest`、`key`（为空默认钥匙卡）
- `top`：`1-x` 今日涨跌、`2-x` 金额、`3-x` 价值、`5-x` 3 日涨跌、`7-x` 7 日涨跌、`30-x` 30 日涨跌（`-1` 小到大，`-2` 大到小）
- `n`：模糊搜索（≤40 字符）、`mid`：地图筛选（1 大坝 2 航天 3 长弓 4 巴克什 5 潮汐监狱）、`grade`：等级、`mtype`：收集品子类
- 额外字段：`ShopSellType`（推荐出售方式：方式名 / 等级 / 秒出价格）；`types=zhanbei` 时增加 `zb_price`、`zb_jz`、`zb_bl`

### 3.4 历史价格曲线

| 接口 | 参数 | 返回 | 覆盖范围 |
| --- | --- | --- | --- |
| `GET /v1/sjz_api/minute` | `id` | `data.a`(时间标签) / `data.b`(价格) / `data.zb` | 24 小时，分钟刻度，最多 1440 点 |
| `GET /v1/sjz_api/hour` | `id` | 同上 | 72 小时（含未来价值预测） |
| `GET /v1/sjz_api/day` | `id` | `data.a` / `data.b` / `max` / `maxD` / `min` / `minD` | 7 / 30 / 45 天，天刻度 |

`a` 与 `b` 是等长数组，按下标一一对应。

## 四、待用户确认 / 待真实 Token 验证

1. **买价与卖价的字段来源**：上述接口只暴露单一 `price` 字段，没有区分买价/卖价。需要确认：
   - 数据帝是否有提供买/卖双价的接口（例如高级接口或官方小程序接口 `playerhub.df.qq.com`）；
   - 若要双价，`price` 应记作哪一侧（最低挂单价 or 卖出到手价）。
2. **`price` 的口径**：是交易行最低挂单价、近期成交价，还是官方小程序展示价？是否需要扣除手续费？
3. **Token 与开通范围**：需要你提供可用 Token，并确认已开通 `item_info_all`、`item_price_all`、`minute/hour/day` 这几个接口。
4. **资源次数余额与上限**：是否有每日总量上限？按每日 4 次全量采集约消耗 80 次/天，是否可接受？
5. **历史曲线接口是否计入 MVP**：若可用，`/api/items/{id}/history` 可以直接透传真实曲线（更精确），也可以只用我们自己积累的快照（更省资源）。当前设计用后者，接口已预留切换空间。
