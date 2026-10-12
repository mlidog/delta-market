"""共享测试夹具。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  导入以注册所有模型
from app.config import get_settings
from app.database import Base, attach_sqlite_pragmas


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    """让测试与开发者本地的 `.env` 解耦。

    测试必须固定使用 mock 数据源：否则一旦本地把 `DATA_SOURCE` 切成 delta，
    断言"当前数据源"的用例就会失败，更糟的是可能真的打到付费接口。
    环境变量优先级高于 `.env`，再清掉配置缓存即可生效。
    """
    monkeypatch.setenv("DATA_SOURCE", "mock")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def engine():
    """每个测试一个独立的内存库，用 StaticPool 让所有会话共享同一个连接。"""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    attach_sqlite_pragmas(test_engine)
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def session(session_factory) -> Session:
    db = session_factory()
    yield db
    db.close()


@pytest.fixture()
def client(session_factory):
    """FastAPI 测试客户端，数据库依赖被替换成内存库。

    故意不用 `with TestClient(...)`：那会触发 lifespan，进而对真实的
    `data/app.db` 建表，测试不该有这种副作用。
    """
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import create_app

    application = create_app()

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = _override_get_db
    yield TestClient(application)
    application.dependency_overrides.clear()
