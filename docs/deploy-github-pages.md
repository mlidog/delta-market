# 部署到 GitHub Pages

> **当前形态（2026-10-14 起）：GitHub 只构建部署，不采集数据。**
> 数据由本机后端每天 0/16/22 点采集并推送，推送即触发部署——线上始终跟着本机走，
> 且不额外消耗数据帝额度。下面第 2~5 步的配置（Secret、Pages Source、写权限）
> 是"整条链路都跑在 GitHub 上"时的做法，现在只有 **Pages Source = GitHub Actions**
> 这一条是必须的，其余留着备查。

## 它是怎么工作的

```
本机后端（每天北京时间 0:00 / 16:00 / 22:00 由 APScheduler 触发）
  ├─ 1. 采集全物品价格 + 制造收益，落库并追加历史快照
  ├─ 2. 导出 frontend/public/data/*.json
  └─ 3. git commit + push
        └─→ GitHub Actions（push 触发，约 1 分钟）
              ├─ npm ci && VITE_STATIC=true npm run build
              ├─ 上传 Pages 产物
              └─ 部署 → https://mlidog.github.io/delta-market/
```

**为什么不让 Actions 自己采集**：GitHub 的 cron 是"尽力而为"，实测迟到 4 小时 55 分到 6 小时 40 分；
更关键的是每次定时触发都会真采一轮（32 次资源），和本机采集完全重复。所以 schedule 与采集步骤都去掉了，
Actions 现在只做它最稳的那部分：构建和部署。

**关键设计：数据库是可丢弃的缓存，JSON 才是持久状态。** 仓库里不需要提交 SQLite 文件，
历史数据以文本形式增量提交，diff 也看得懂。

## 部署步骤（首次配置时用，供参考）

1. **建仓库并推送代码**

```powershell
cd C:\Users\84439\Documents\ChatGPT\deltaproject
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

2. **配置 Token Secret**

仓库 → Settings → Secrets and variables → Actions → New repository secret

名称 `DELTA_API_TOKEN`，值为数据帝控制台里的密钥。

3. **打开 Pages**

仓库 → Settings → Pages → Build and deployment → Source 选 **GitHub Actions**。

4. **打开工作流写权限**

仓库 → Settings → Actions → General → Workflow permissions → 选 **Read and write permissions**
（工作流要把数据快照提交回仓库；不打开的话部署能成功，但历史不会累积）。

5. **手动跑一次验证**

仓库 → Actions → 「更新数据并部署看板」→ Run workflow。

完成后访问 `https://<你的用户名>.github.io/<仓库名>/`。

## 与本地版的差别

| 功能 | 本地版 | Pages 静态版 |
| --- | --- | --- |
| 物品行情、筛选、排序、搜索 | 后端查询 | 浏览器内计算 |
| 历史曲线 | 有 | 有（30 天，来自提交的 history.json） |
| 制造排行、分页、图标 | 有 | 有 |
| 手动同步按钮 | 有 | 无（数据由本机定时采集后推送） |
| 采集频次 | 本机 0/16/22 点 | 同左（Actions 不采集，只在本机推送后重建约 1 分钟） |
| 历史保留 | 无上限 | 30 天 |

## 注意事项

- **别在提交信息里加 `[skip ci]`**：GitHub 会跳过整次推送，网页就停在旧数据上。
  发布器的默认提交信息是 `chore: 更新数据快照`，没有这个关键字。
- **Actions 免费额度**：公开仓库免费；私有仓库每月 2000 分钟，这个工作流每次约 1 分钟，
  一天三次绰绰有余。
- **资源消耗只在本机**：每轮 32 次资源，一天 3 轮共 96 次；Actions 这边 0 次。
- 仓库会持续新增数据快照提交（一天 3 次）。
