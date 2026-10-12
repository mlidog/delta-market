"""系统级响应模型。"""

from __future__ import annotations

from app.schemas.common import UtcDateTime, UtcModel


class HealthOut(UtcModel):
    status: str
    app: str
    version: str
    database: str
    data_source: str
    scheduler_running: bool
    next_collect_at: UtcDateTime | None = None
    server_time: UtcDateTime
