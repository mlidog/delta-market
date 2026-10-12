"""按配置选择数据源。"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.data_sources.base import DataSource, DataSourceError
from app.data_sources.mock import MockDataSource


def create_data_source(settings: Settings | None = None) -> DataSource:
    """根据 `DATA_SOURCE` 配置创建数据源实例。

    `delta` 分支在 M6 实现；在此之前给出明确报错，而不是静默回退到 mock，
    避免"以为在用真实数据、其实在用模拟数据"这种最难排查的问题。
    """
    config = settings or get_settings()

    if config.data_source == "mock":
        return MockDataSource()

    if config.data_source == "delta":
        from app.data_sources.delta import DeltaDataSource  # 延迟导入，M6 提供

        return DeltaDataSource(
            base_url=config.delta_api_base_url,
            token=config.delta_api_token_value,
            timeout=config.delta_api_timeout,
        )

    raise DataSourceError(f"未知的 DATA_SOURCE: {config.data_source!r}")
