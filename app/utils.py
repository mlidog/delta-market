"""通用小工具。"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """返回**不带时区信息**的 UTC 当前时间。

    SQLite 不保存时区，统一约定：库里所有时间字段都是 UTC 的 naive datetime，
    由 API 层负责序列化，前端负责换算成北京时间展示。
    """
    return datetime.now(UTC).replace(tzinfo=None)
