"""数据库引擎与会话管理。"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_DIR = PROJECT_ROOT / "db"
DATABASE_FILE = DATABASE_DIR / "ai_coding.db"

DATABASE_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATABASE_FILE.as_posix()}"

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
