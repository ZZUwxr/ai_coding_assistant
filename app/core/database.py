"""数据库引擎与会话管理。"""

from __future__ import annotations

from collections.abc import Generator

from sqlmodel import SQLModel, Session, create_engine

DATABASE_URL = "sqlite:///./ai_coding.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


def create_db_and_tables() -> None:
    """创建数据库与所有 SQLModel 表。"""

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """为 FastAPI 路由提供数据库会话。"""

    with Session(engine) as session:
        yield session
