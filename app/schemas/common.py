"""响应模型公共约定。"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, field_serializer

#: 可能出现在响应里的时间字段名，统一按 UTC ISO8601（带 Z）输出。
#: 一定要带时区标记：裸时间字符串会被前端 `new Date()` 当成**本地时间**解析。
_DATETIME_FIELDS = (
    "t",
    "server_time",
    "updated_at",
    "source_updated_at",
    "generated_at",
    "started_at",
    "finished_at",
)


def to_utc_iso(value: datetime | None) -> str | None:
    """把库里的 naive UTC 时间转成带 `Z` 的 ISO8601 字符串。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class UtcModel(BaseModel):
    """时间字段统一序列化的基类。"""

    @field_serializer(*_DATETIME_FIELDS, when_used="json", check_fields=False)
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return to_utc_iso(value)
