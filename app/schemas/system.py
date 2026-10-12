"""系统级响应模型。"""

from __future__ import annotations

from datetime import datetime

from app.schemas.common import UtcModel


class HealthOut(UtcModel):
    status: str
    app: str
    version: str
    database: str
    data_source: str
    scheduler_running: bool
    server_time: datetime
