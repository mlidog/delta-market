"""M0 冒烟测试：确认运行环境与依赖可用。"""

import sys


def test_python_version_at_least_311() -> None:
    assert sys.version_info >= (3, 11), f"需要 Python 3.11+，当前为 {sys.version}"


def test_core_dependencies_importable() -> None:
    import apscheduler  # noqa: F401
    import fastapi  # noqa: F401
    import httpx  # noqa: F401
    import pydantic_settings  # noqa: F401
    import sqlalchemy  # noqa: F401
    import tenacity  # noqa: F401
