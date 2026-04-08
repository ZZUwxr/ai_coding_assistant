"""Task API 路由定义，使用内存字典模拟任务状态流转。"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.models.schemas import ApprovalRequest, TaskCreateRequest, TaskResponse, TaskStatus, utc_now
from app.services.workflow import process_task_pipeline

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

# 使用内存字典模拟数据库，便于在业务逻辑未完成前跑通接口。
fake_db: dict[str, TaskResponse] = {}


def get_task_or_404(task_id: str) -> TaskResponse:
    """根据任务 ID 获取任务，不存在时抛出 404。"""

    task = fake_db.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )
    return task


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreateRequest, background_tasks: BackgroundTasks) -> TaskResponse:
    """创建任务并将其初始化为计划中状态。"""

    now = utc_now()
    task = TaskResponse(
        task_id=str(uuid4()),
        requirement=payload.requirement,
        status=TaskStatus.PLANNING,
        created_at=now,
        updated_at=now,
    )
    fake_db[task.task_id] = task
    background_tasks.add_task(process_task_pipeline, task.task_id)
    return task


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> TaskResponse:
    """获取指定任务的当前详情与状态。"""

    return get_task_or_404(task_id)


@router.post("/{task_id}/approve", response_model=TaskResponse)
async def approve_task(
    task_id: str,
    payload: ApprovalRequest,
    background_tasks: BackgroundTasks,
) -> TaskResponse:
    """处理人工审批结果，并驱动任务进入下一状态。"""

    task = get_task_or_404(task_id)

    if task.status != TaskStatus.WAITING_FOR_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task is not waiting for approval.",
        )

    if payload.is_approved:
        task.status = TaskStatus.PROCESSING
    else:
        task.status = TaskStatus.PLANNING
        task.code_draft = None
        task.review_report = None
        task.plan = {
            **(task.plan or {}),
            "approval_feedback": payload.feedback or "Human approval rejected without detailed feedback.",
        }

    task.updated_at = utc_now()

    fake_db[task_id] = task
    background_tasks.add_task(process_task_pipeline, task_id)
    return task
