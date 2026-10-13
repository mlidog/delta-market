"""发布静态数据到 GitHub 的测试。

用真实的临时 git 仓库（本地裸仓库当远端）跑完整流程，
不联网、不消耗任何资源，但走的是与生产完全相同的 git 调用路径。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.publisher import (
    DATA_PATH,
    publish_site_data,
    system_proxy,
)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """一个带裸远端（bare remote）的临时仓库。"""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "--quiet", str(remote))

    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "--quiet", "-b", "main")
    git(work, "config", "user.name", "tester")
    git(work, "config", "user.email", "tester@example.com")
    git(work, "remote", "add", "origin", str(remote))

    (work / DATA_PATH).mkdir(parents=True)
    (work / DATA_PATH / "meta.json").write_text('{"v":1}', encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "--quiet", "-m", "init")
    git(work, "push", "--quiet", "-u", "origin", "main")
    return work


def writer(payload: str):
    def _export() -> dict[str, int]:
        (Path.cwd() / DATA_PATH).mkdir(parents=True, exist_ok=True)
        path = Path.cwd() / DATA_PATH / "meta.json"
        path.write_text(payload, encoding="utf-8")
        return {"meta.json": len(payload)}

    return _export


class TestPublish:
    def test_skips_when_repository_has_no_remote(self, tmp_path: Path) -> None:
        work = tmp_path / "solo"
        work.mkdir()
        git(work, "init", "--quiet", "-b", "main")

        result = publish_site_data(repo_dir=work, exporter=lambda: {})

        assert result.skipped is True
        assert result.committed is False
        assert result.error is None

    def test_commits_and_pushes_new_data(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        result = publish_site_data(repo_dir=repo, exporter=writer('{"v":2}'))

        assert result.ok, result.error
        assert result.committed is True
        assert result.pushed is True
        assert result.used_proxy is False

        log = git(repo, "log", "--oneline", "-1").stdout
        assert "更新数据快照" in log
        # 远端也收到了这次提交
        remote_log = git(repo, "log", "--oneline", "-1", "origin/main").stdout
        assert "更新数据快照" in remote_log

    def test_no_changes_means_no_commit(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        first = publish_site_data(repo_dir=repo, exporter=writer('{"v":2}'))
        assert first.committed is True

        # 同样的内容再导出一次：不应该产生新提交
        second = publish_site_data(repo_dir=repo, exporter=writer('{"v":2}'))
        assert second.committed is False
        assert second.pushed is False
        assert second.ok

    def test_export_failure_is_reported(self, repo: Path) -> None:
        def boom() -> dict[str, int]:
            raise RuntimeError("导出炸了")

        result = publish_site_data(repo_dir=repo, exporter=boom)

        assert result.ok is False
        assert "导出炸了" in (result.error or "")
        assert result.committed is False

    def test_custom_commit_message(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        publish_site_data(repo_dir=repo, exporter=writer('{"v":3}'), message="chore: 手工发布")
        assert "手工发布" in git(repo, "log", "--oneline", "-1").stdout


class TestSystemProxy:
    def test_reads_environment_variable_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1234")
        assert system_proxy() == "http://127.0.0.1:1234"

    def test_returns_none_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            monkeypatch.delenv(name, raising=False)
        # 注册表里 ProxyEnable 关掉时（或读不到）应返回 None
        monkeypatch.setattr("winreg.OpenKey", lambda *a, **k: (_ for _ in ()).throw(OSError()))
        assert system_proxy() is None
