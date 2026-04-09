"""FastAPI 应用入口与路由挂载定义。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router as task_router
from app.core.database import create_db_and_tables


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用启动时初始化数据库表。"""

    create_db_and_tables()
    yield


app = FastAPI(title="AI Coding Assistant API", lifespan=lifespan)


@app.get("/")
async def root() -> dict[str, str]:
    """服务健康探针接口。"""

    return {"status": "ok", "message": "AI Coding Assistant API is running"}


app.include_router(task_router)
