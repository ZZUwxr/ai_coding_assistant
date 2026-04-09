"""数据库模型与 API 数据模型定义。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Column, DateTime, String, Text
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


def utc_now() -> datetime:
    """返回带时区信息的 UTC 当前时间。"""

    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    """任务在工作流中的状态枚举。"""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TaskRecord(SQLModel, table=True):
    """任务持久化数据库模型。"""

    __tablename__ = "tasks"

    task_id: str = SQLField(
        sa_column=Column(String, primary_key=True, nullable=False),
        description="任务唯一标识，使用 UUID 字符串。",
    )
    requirement: str = SQLField(
        sa_column=Column(Text, nullable=False),
        description="用户提交的研发需求文本。",
    )
    status: str = SQLField(
        sa_column=Column(String, nullable=False),
        description="当前任务状态字符串。",
    )
    plan: dict[str, Any] | None = SQLField(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Planner 输出的计划结果。",
    )
    code_draft: str | None = SQLField(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Coder 输出的代码草稿。",
    )
    review_report: dict[str, Any] | None = SQLField(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Reviewer 输出的审查报告。",
    )
    created_at: datetime = SQLField(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
        description="任务创建时间。",
    )
    updated_at: datetime = SQLField(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
        description="任务最近更新时间。",
    )


class TaskCreateRequest(BaseModel):
    """创建研发任务时的请求体。"""

    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(..., description="用户提交的研发需求文本。", min_length=1)


class ApprovalRequest(BaseModel):
    """人类审批任务时的请求体。"""

    model_config = ConfigDict(extra="forbid")

    is_approved: bool = Field(..., description="审批是否通过。")
    feedback: str | None = Field(default=None, description="审批意见或补充说明。")


class TaskResponse(BaseModel):
    """任务详情响应体。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., description="任务唯一标识，使用 UUID 字符串。")
    requirement: str = Field(..., description="用户提交的研发需求文本。")
    status: TaskStatus = Field(..., description="当前任务状态。")
    plan: dict[str, Any] | None = Field(default=None, description="Planner 输出的计划结果。")
    code_draft: str | None = Field(default=None, description="Coder 输出的代码草稿。")
    review_report: dict[str, Any] | None = Field(default=None, description="Reviewer 输出的审查报告。")
    created_at: datetime = Field(default_factory=utc_now, description="任务创建时间。")
    updated_at: datetime = Field(default_factory=utc_now, description="任务最近更新时间。")


class PlannerOutput(BaseModel):
    """Planner Agent 的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    thinking_process: str = Field(..., description="需求拆解的核心思考过程。")
    execution_steps: list[str] = Field(..., description="可执行的分步骤计划。")
    target_files: list[str] = Field(..., description="预计会涉及的目标文件列表。")


class ContextOutput(BaseModel):
    """Context Agent 的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    relevant_code: list[dict[str, str]] = Field(
        ...,
        description="与需求相关的现有代码上下文，元素包含 filename 和 content。",
    )
    analysis: str = Field(..., description="对现有上下文、依赖和潜在冲突的分析。")


class CodeDraftOutput(BaseModel):
    """Coder Agent 的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    code_snippets: list[dict[str, str]] = Field(
        ...,
        description="生成的代码片段列表，元素包含 filename 和 content。",
    )


class ReviewReport(BaseModel):
    """Reviewer Agent 的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    is_passed: bool = Field(..., description="代码是否通过审查。")
    issues_found: int = Field(..., description="发现的问题数量。", ge=0)
    comments: list[str] = Field(..., description="具体的审查意见与修改建议。")


def task_record_to_response(record: TaskRecord) -> TaskResponse:
    """将数据库记录转换为 API 响应模型。"""

    return TaskResponse(
        task_id=record.task_id,
        requirement=record.requirement,
        status=TaskStatus(record.status),
        plan=record.plan,
        code_draft=record.code_draft,
        review_report=record.review_report,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def create_task_record(
    task_id: str,
    requirement: str,
    status: TaskStatus = TaskStatus.PLANNING,
    plan: dict[str, Any] | None = None,
    code_draft: str | None = None,
    review_report: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> TaskRecord:
    """创建新的任务数据库记录。"""

    created_time = created_at or utc_now()
    updated_time = updated_at or created_time

    return TaskRecord(
        task_id=task_id,
        requirement=requirement,
        status=status.value,
        plan=plan,
        code_draft=code_draft,
        review_report=review_report,
        created_at=created_time,
        updated_at=updated_time,
    )
