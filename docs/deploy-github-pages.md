# 部署到 GitHub Pages（方案 A）

> ⚠️ **2026-10-14 已移除**：`.github/workflows/pages.yml` 被删除，本机采集是唯一的更新路径。
> 因此线上站点（`https://mlidog.github.io/delta-market/`）**不再自动重建**：本机推送到仓库的
> 新数据和新前端代码都不会反映到线上，页面停在最后一次成功部署的版本。
>
> 需要恢复时：`git checkout 37457f3 -- .github/workflows/pages.yml`，然后按下面的步骤
> 重新配置 Secret 与 Pages（仓库设置不会因为删文件而改变）。
>
> 移除原因：GitHub 的 cron 不保证准时（实测迟到 5~6.7 小时），且每次触发都会真采一轮
> （32 次资源），与本机采集重复消耗额度。

目标：**整条链路都跑在 GitHub 上**，不依赖你自己的电脑——Actions 定时调数据帝接口、
导出静态 JSON、构建前端并发布。你只需要一台能打开网页的设备。

## 它是怎么工作的

```
GitHub Actions（每天 3 次，北京时间 16:00 / 22:00 / 次日 00:00）
  ├─ 1. 用仓库里上一次的 items.json / history.json 预热数据库
  │     （否则每轮都要重新拉全量物品目录，白花 20 次资源）
  ├─ 2. 调数据帝：全物品价格（20 次资源）+ 制造收益（12 次资源）
  ├─ 3. 导出 frontend/public/data/*.json
  ├─ 4. 构建前端（VITE_STATIC=true）并发布到 Pages
  └─ 5. 把 JSON 快照提交回仓库（下一次运行就靠它"记得"历史）
```

**关键设计：数据库是可丢弃的缓存，JSON 才是持久状态。** 仓库里不需要提交 SQLite 文件，
历史数据以文本形式增量提交，diff 也看得懂。

## 部署步骤

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
| 手动同步按钮 | 有 | 无（数据由 Actions 定时更新） |
| 采集频次 | 本机 0/16/22 点 | Actions cron，**可能延迟几分钟到几十分钟** |
| 历史保留 | 无上限 | 30 天 |

## 注意事项

- **Actions 的定时任务不是精确闹钟**，高负载时可能延迟甚至偶尔跳过。行情看板对时效要求不高，够用。
- **免费额度**：公开仓库的 Actions 免费；私有仓库每月 2000 分钟，这个工作流每次约 1-2 分钟，一天 3 次绰绰有余。
- **资源消耗与本地版一致**：每轮 32 次资源，一天 3 轮共 96 次。
- 仓库会持续新增数据快照提交（一天 3 次）。介意提交历史的话，可以让工作流只提交
  `items.json` 与 `history.json`，其余每次重新生成。
