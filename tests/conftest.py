"""共享测试夹具。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  导入以注册所有模型
from app.database import Base, attach_sqlite_pragmas


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
