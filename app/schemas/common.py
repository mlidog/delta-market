"""响应模型公共约定。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, PlainSerializer


def to_utc_iso(value: datetime | None) -> str | None:
    """把库里的 naive UTC 时间转成带 `Z` 的 ISO8601 字符串。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class UtcModel(BaseModel):
    """响应模型基类。

    时间字段**必须**声明为 `UtcDateTime`（或 `UtcDateTime | None`），
    不要写成裸 `datetime`——裸时间会被前端 `new Date()` 当成**本地时间**解析，
    在东八区会整体偏 8 小时。
    """


#: 带 UTC 标记（结尾 `Z`）的 ISO8601 时间字段。
#: 用类型而不是"字段名清单"来驱动序列化：清单漏一个字段就静默出错，
#: 而类型写错会立刻在类型检查或断言里暴露。
UtcDateTime = Annotated[
    datetime,
    PlainSerializer(to_utc_iso, return_type=str, when_used="json"),
]
