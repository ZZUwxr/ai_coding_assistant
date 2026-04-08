"""FastAPI 应用入口与路由挂载定义。"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router as task_router

app = FastAPI(title="AI Coding Assistant API")


@app.get("/")
async def root() -> dict[str, str]:
    """服务健康探针接口。"""

    return {"status": "ok", "message": "AI Coding Assistant API is running"}


app.include_router(task_router)
