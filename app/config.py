"""应用配置。

所有可变配置统一从环境变量 / `.env` 读取，业务代码通过 :func:`get_settings` 获取单例，
避免在代码里散落硬编码的地址、密钥或路径。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

#: 默认采集时刻：0 点（游戏每日价格重置，可捕获开盘价）、16 点、22 点
DEFAULT_CRON_HOURS = [0, 16, 22]


class Settings(BaseSettings):
    """运行时配置，字段名与 `.env` 中的变量名一一对应（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 应用 ---
    app_name: str = "三角洲物价观察"
    app_env: str = "dev"
    log_level: str = "INFO"

    # --- 数据源 ---
    data_source: Literal["mock", "delta"] = "mock"
    delta_api_base_url: str = "https://orzice.com/workApi"
    delta_api_token: SecretStr = SecretStr("")
    delta_api_timeout: float = 10.0

    # --- 数据库 ---
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}"

    # --- 采集 ---
    collector_timezone: str = "Asia/Shanghai"
    #: 是否在本进程内启动定时采集。多 worker 部署时应只让一个进程开启，
    #: 或干脆关闭、由外部调度器调用采集命令。
    scheduler_enabled: bool = True
    # 用 NoDecode 关闭 pydantic-settings 的 JSON 解析，才能接受 `0,16,22` 这种写法
    collector_cron_hours: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_CRON_HOURS)
    )
    collector_retry_times: int = 3
    collector_run_on_startup: bool = True
    #: 物品基础信息的刷新间隔（天）。`item_info_all` 与 `item_price_all` 各消耗
    #: 20 次资源，而名称/分类/格数几乎不变，所以默认一周拉一次即可；
    #: 设为 0 表示每轮都刷新。
    collector_item_refresh_days: int = 7

    @field_validator("collector_cron_hours", mode="before")
    @classmethod
    def _parse_cron_hours(cls, value: object) -> object:
        """支持 `.env` 中的 `0,16,22`（含中文逗号与空格）。"""
        if isinstance(value, str):
            parts = value.replace("，", ",").split(",")
            return [int(part.strip()) for part in parts if part.strip()]
        return value

    @field_validator("collector_cron_hours")
    @classmethod
    def _check_cron_hours(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("COLLECTOR_CRON_HOURS 不能为空")
        if any(hour < 0 or hour > 23 for hour in value):
            raise ValueError("COLLECTOR_CRON_HOURS 必须是 0~23 的整数")
        return sorted(set(value))

    @property
    def delta_api_token_value(self) -> str:
        """取出明文 Token；仅在数据源内部使用，不要写日志。"""
        return self.delta_api_token.get_secret_value()

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    """返回配置单例。"""
    return Settings()
