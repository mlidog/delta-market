"""数据库连接、会话与建表。

MVP 使用 SQLite；后续切换 PostgreSQL / TimescaleDB 只需改 `DATABASE_URL`。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BASE_DIR, get_settings

SQLITE_PREFIX = "sqlite:///"


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def normalize_sqlite_url(url: str) -> str:
    """把 `sqlite:///./data/app.db` 这类相对路径固定到项目根目录。

    这样无论从哪个目录启动进程，数据库文件位置都一致。
    """
    if not url.startswith(SQLITE_PREFIX):
        return url
    raw = url[len(SQLITE_PREFIX) :]
    if not raw or raw == ":memory:":
        return url
    path = Path(raw)
    if path.is_absolute():
        return url
    return f"{SQLITE_PREFIX}{(BASE_DIR / path).resolve().as_posix()}"


settings = get_settings()
database_url = normalize_sqlite_url(settings.database_url)
is_sqlite = database_url.startswith(SQLITE_PREFIX)

if is_sqlite:
    db_path = database_url[len(SQLITE_PREFIX) :]
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    database_url,
    # SQLite 默认禁止跨线程复用连接，而 FastAPI 的同步依赖会在工作线程里执行
    connect_args={"check_same_thread": False} if is_sqlite else {},
    future=True,
)

if is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        """SQLite 默认不强制外键，这里按连接显式打开。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个数据库会话。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """创建所有尚不存在的表。"""
    # 导入模型模块，确保它们已注册到 Base.metadata
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
