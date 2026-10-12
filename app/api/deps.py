"""接口层公共依赖。"""

from __future__ import annotations

from collections.abc import Iterator

from app.data_sources import DataSource, create_data_source


def data_source_dependency() -> Iterator[DataSource]:
    """按配置提供数据源，并在请求结束后关闭它。

    做成依赖而不是在路由里 new：测试可以覆盖它，避免测试意外打到真实付费接口。
    """
    source = create_data_source()
    try:
        yield source
    finally:
        source.close()
