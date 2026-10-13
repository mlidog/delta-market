"""把静态数据发布到 GitHub（GitHub Pages 的数据来源）。

本机后端每天 0/16/22 采集完成后调用：导出 JSON → 提交 → 推送。
推送先试直连，失败再自动改用系统代理重试——国内直连 github.com 经常连不上，
而 **git 默认不使用 Windows 的系统代理**（只有浏览器/.NET 会用），这一步兜住它。

GitHub Actions 里也有同样的导出逻辑，所以两条路互为备份：

* 本机在线时：本机采集 + 推送（准时）
* 本机离线时：Actions 的定时任务（GitHub 的 cron 是尽力而为，可能延迟很久）
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

#: 数据快照所在路径（相对仓库根目录）
DATA_PATH = "frontend/public/data"
REMOTE = "origin"
BRANCH = "main"
GIT_TIMEOUT_SECONDS = 180


@dataclass(slots=True)
class PublishResult:
    exported: dict[str, int] = field(default_factory=dict)
    committed: bool = False
    pushed: bool = False
    skipped: bool = False
    used_proxy: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def system_proxy() -> str | None:
    """读取系统代理地址。

    git 不会自动使用 Windows 的系统代理，所以这里手动读出来，
    在直连失败时作为重试通道。先看环境变量，再看注册表。
    """
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(name)
        if value:
            return value.strip()

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return None
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except (OSError, ImportError, FileNotFoundError):
        return None

    if not server:
        return None
    text = str(server)
    # 可能是 "host:port"，也可能是 "http=host:port;https=host:port"
    if "=" in text:
        parts = dict(
            item.split("=", 1) for item in text.split(";") if "=" in item
        )
        text = parts.get("https") or parts.get("http") or ""
    if not text:
        return None
    return text if text.startswith("http") else f"http://{text}"


def _sync_with_remote(repo_dir: Path | None) -> str | None:
    """把远端比本地新的提交合并进来（数据文件冲突以本地为准）。返回错误信息。

    拉取失败时返回 None 而不是报错：网络不通时先让推送去试，
    推送被拒（说明远端确实更新了）时会再调一次这个函数。
    """
    fetch = _git(["fetch", REMOTE, BRANCH], repo_dir=repo_dir)
    if fetch.returncode != 0:
        return None

    behind = _git(["rev-list", "--count", f"HEAD..{REMOTE}/{BRANCH}"], repo_dir=repo_dir)
    try:
        pending = int((behind.stdout or "0").strip())
    except ValueError:
        pending = 0
    if pending <= 0:
        return None

    logger.info("远端有 %d 个本地没有的提交，先合并（数据冲突以本地为准）", pending)
    merge = _git(
        ["merge", "--no-edit", "-X", "ours", f"{REMOTE}/{BRANCH}"], repo_dir=repo_dir
    )
    if merge.returncode != 0:
        _git(["merge", "--abort"], repo_dir=repo_dir)
        return f"合并远端失败：{(merge.stderr or merge.stdout).strip()[:200]}"
    return None


def _git(
    args: list[str],
    *,
    proxy: str | None = None,
    capture: bool = True,
    repo_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["git"]
    if proxy:
        command += ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
    command += args

    env = dict(os.environ)
    # 需要凭据时直接失败，而不是弹出交互式窗口把任务挂死
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        command,
        cwd=repo_dir or BASE_DIR,
        env=env,
        capture_output=capture,
        text=True,
        # 必须显式指定 UTF-8：git 的输出（提交信息、文件名）是 UTF-8，
        # 而 Windows 中文环境下 subprocess 默认按 GBK 解码，会直接抛 UnicodeDecodeError
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )


def publish_site_data(
    *,
    collect_data: bool = False,
    message: str | None = None,
    repo_dir: Path | None = None,
    exporter: Callable[[], dict[str, int]] | None = None,
) -> PublishResult:
    """导出静态数据并推送到 GitHub。采集本身由调度器负责，这里默认只导出。"""
    result = PublishResult()
    if not get_settings().publisher_enabled:
        result.skipped = True
        return result

    remote = _git(["remote", "get-url", REMOTE], repo_dir=repo_dir)
    if remote.returncode != 0:
        result.skipped = True
        logger.info("仓库没有配置远端 %s，跳过发布", REMOTE)
        return result

    try:
        if exporter is None:
            # 延迟导入：scripts 不是安装包，只在真正发布时才需要
            from scripts.export_static import export_site

            result.exported = export_site(collect_data=collect_data, verbose=False)
        else:
            result.exported = exporter()
    except Exception as exc:  # 导出失败不该拖垮采集任务
        result.error = f"导出静态数据失败：{exc}"
        logger.exception("导出静态数据失败")
        return result

    _git(["add", "--", DATA_PATH], repo_dir=repo_dir)
    staged = _git(["diff", "--cached", "--name-only"], repo_dir=repo_dir)
    if not staged.stdout.strip():
        logger.info("数据没有变化，跳过提交")
        return result

    commit = _git(
        ["commit", "-m", message or "chore: 更新数据快照 [skip ci]"], repo_dir=repo_dir
    )
    if commit.returncode != 0:
        result.error = f"提交失败：{(commit.stderr or commit.stdout).strip()[:200]}"
        return result
    result.committed = True

    # 推送前先把远端拉下来合并：GitHub Actions 偶尔也会提交数据快照，
    # 两边都改同一批生成出来的 JSON，必然冲突。数据以本机为准（刚导出，最新），
    # 所以冲突块取本地版本（-X ours）；远端对其它文件的改动照常合并进来。
    sync_error = _sync_with_remote(repo_dir)
    if sync_error:
        result.error = sync_error
        logger.warning("%s", result.error)
        return result

    push = _git(["push", REMOTE, BRANCH], repo_dir=repo_dir)
    if push.returncode == 0:
        result.pushed = True
        return result

    # 被拒通常意味着"远端在刚才这几秒里又前进了"（对手提交了数据快照），
    # 重新同步一次就能推上去；不行再去折腾代理。
    if "fetch first" in (push.stderr or "") or "non-fast-forward" in (push.stderr or ""):
        logger.info("推送被拒（远端有更新），重新同步后再试")
        if _sync_with_remote(repo_dir) is None:
            retry_push = _git(["push", REMOTE, BRANCH], repo_dir=repo_dir)
            if retry_push.returncode == 0:
                result.pushed = True
                return result
            push = retry_push

    proxy = system_proxy()
    if proxy is None:
        result.error = f"推送失败（直连，且未找到系统代理）：{(push.stderr or '').strip()[:200]}"
        logger.warning("推送失败且没有可用代理：%s", result.error)
        return result

    logger.info("直连推送失败，改用系统代理 %s 重试", proxy)
    retry = _git(["push", REMOTE, BRANCH], proxy=proxy, repo_dir=repo_dir)
    result.pushed = retry.returncode == 0
    result.used_proxy = result.pushed
    if not result.pushed:
        result.error = f"走代理推送仍失败：{(retry.stderr or '').strip()[:200]}"
        logger.warning("%s", result.error)
    return result
