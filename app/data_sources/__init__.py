"""可插拔数据源。

约定：**所有外部 HTTP 调用都必须封装在本包内**，业务代码只依赖 `base.py` 定义的
接口与数据结构。换数据源时，理论上只需要新增一个模块并在 `registry.py` 注册。
"""

from app.data_sources.base import (
    DataSource,
    DataSourceAuthError,
    DataSourceError,
    DataSourceRateLimitError,
    DataSourceResponseError,
    DataSourceUnavailableError,
    ItemRecord,
    PriceRecord,
)
from app.data_sources.mock import MockDataSource
from app.data_sources.registry import create_data_source

__all__ = [
    "DataSource",
    "DataSourceAuthError",
    "DataSourceError",
    "DataSourceRateLimitError",
    "DataSourceResponseError",
    "DataSourceUnavailableError",
    "ItemRecord",
    "MockDataSource",
    "PriceRecord",
    "create_data_source",
]
