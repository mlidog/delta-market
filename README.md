# 三角洲物价观察

《三角洲行动》交易行物价观察工具。当前处于 **后端 MVP** 阶段。

## 里程碑进度

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M0 | 仓库初始化、依赖、测试框架 | 完成 |
| M1 | 配置、数据库、ORM 模型 | 完成 |
| M2 | 数据源抽象层 + MockDataSource | 未开始 |
| M3 | 采集服务（写入价格快照） | 未开始 |
| M4 | 四个 API 接口 | 未开始 |
| M5 | 定时任务（每日 0/8/18/22 点） | 未开始 |
| M6 | DeltaDataSource（真实数据帝 API） | 未开始 |
| M7 | 前端看板 | 未开始 |

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
- 数据帝 API 按"资源次数"计费，全量价格接口单次约消耗 20 次资源。
