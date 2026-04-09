"""Task API 路由定义，使用 SQLite 持久化任务状态。"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.core.database import get_session
from app.models.schemas import (
    ApprovalRequest,
    TaskCreateRequest,
    TaskRecord,
    TaskResponse,
    TaskStatus,
    create_task_record,
    task_record_to_response,
    utc_now,
)
from app.services.workflow import process_task_pipeline
from app.services.pubsub import stream_manager

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def get_task_or_404(task_id: str, session: Session) -> TaskRecord:
    """根据任务 ID 获取任务，不存在时抛出 404。"""

    task = session.get(TaskRecord, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )
    return task


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> TaskResponse:
    """创建任务并将其初始化为计划中状态。"""

    now = utc_now()
    record = create_task_record(
        task_id=str(uuid4()),
        requirement=payload.requirement,
        status=TaskStatus.PLANNING,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    background_tasks.add_task(process_task_pipeline, record.task_id)
    return task_record_to_response(record)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, session: Session = Depends(get_session)) -> TaskResponse:
    """获取指定任务的当前详情与状态。"""

    task = get_task_or_404(task_id, session)
    return task_record_to_response(task)


@router.get("/{task_id}/stream")
async def stream_task_events(task_id: str, session: Session = Depends(get_session)) -> StreamingResponse:
    """返回指定任务的 SSE 事件流。"""

    get_task_or_404(task_id, session)
    return StreamingResponse(
        stream_manager.subscribe(task_id),
        media_type="text/event-stream",
    )


@router.post("/{task_id}/approve", response_model=TaskResponse)
async def approve_task(
    task_id: str,
    payload: ApprovalRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> TaskResponse:
    """处理人工审批结果，并驱动任务进入下一状态。"""

    task = get_task_or_404(task_id, session)

    if task.status != TaskStatus.WAITING_FOR_APPROVAL.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task is not waiting for approval.",
        )

    if payload.is_approved:
        task.status = TaskStatus.PROCESSING.value
    else:
        task.status = TaskStatus.PLANNING.value
        task.code_draft = None
        task.review_report = None
        task.plan = {
            **(task.plan or {}),
            "approval_feedback": payload.feedback or "人工审批未通过，且未提供详细反馈。",
        }

    task.updated_at = utc_now()

    session.add(task)
    session.commit()
    session.refresh(task)
    background_tasks.add_task(process_task_pipeline, task_id)
    return task_record_to_response(task)
