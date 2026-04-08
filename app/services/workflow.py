"""串联各 Agent 并处理审批中断的工作流模块。"""

from __future__ import annotations

import logging

from app.agents.coder import run_coder_agent
from app.agents.context import run_context_agent
from app.agents.planner import run_planner_agent
from app.agents.reviewer import run_reviewer_agent
from app.agents.utils import safe_resolve_workspace_path
from app.models.schemas import PlannerOutput, TaskResponse, TaskStatus, utc_now

logger = logging.getLogger(__name__)

MAX_REVIEW_RETRIES = 3


def _get_task_storage() -> dict[str, TaskResponse]:
    """延迟读取任务存储，避免与路由层形成循环导入。"""

    from app.api.routes import fake_db

    return fake_db


def _get_task(task_id: str) -> TaskResponse | None:
    """根据任务 ID 获取任务。"""

    return _get_task_storage().get(task_id)


def _persist_task(task: TaskResponse) -> None:
    """将任务写回内存存储并刷新更新时间。"""

    task.updated_at = utc_now()
    _get_task_storage()[task.task_id] = task


def _mark_task_failed(task: TaskResponse, reason: str) -> None:
    """将任务标记为失败，并写入失败原因。"""

    logger.exception("Task '%s' failed: %s", task.task_id, reason)
    task.status = TaskStatus.FAILED
    task.review_report = {
        "is_passed": False,
        "issues_found": 1,
        "comments": [reason],
    }
    _persist_task(task)


def _build_planner_requirement(task: TaskResponse) -> str:
    """将审批反馈合并到 Planner 输入中。"""

    planner_requirement = task.requirement
    approval_feedback = (task.plan or {}).get("approval_feedback")
    if approval_feedback:
        planner_requirement = (
            f"{planner_requirement}\n\n"
            "Additional human feedback for replanning:\n"
            f"{approval_feedback}"
        )
    return planner_requirement


def _build_coder_requirement(base_requirement: str, review_comments: list[str] | None) -> str:
    """将历史审查意见合并到 Coder 输入中。"""

    if not review_comments:
        return base_requirement

    return (
        f"{base_requirement}\n\n"
        "Previous review feedback that must be fixed in this attempt:\n"
        + "\n".join(f"- {comment}" for comment in review_comments)
    )


async def _run_planning_stage(task: TaskResponse) -> None:
    """执行规划阶段，生成计划并等待人工审批。"""

    planner_output = await run_planner_agent(
        requirement=_build_planner_requirement(task),
    )
    task.plan = planner_output.model_dump()
    task.code_draft = None
    task.review_report = None
    task.status = TaskStatus.WAITING_FOR_APPROVAL
    _persist_task(task)


async def _run_processing_stage(task: TaskResponse) -> None:
    """执行上下文提取、编码与审查循环。"""

    if not task.plan:
        raise ValueError("Task plan is missing before processing.")

    plan = PlannerOutput.model_validate(task.plan)
    context_output = await run_context_agent(
        requirement=task.requirement,
        execution_steps=plan.execution_steps,
        target_files=plan.target_files,
    )

    review_comments: list[str] | None = None

    for attempt in range(1, MAX_REVIEW_RETRIES + 1):
        coder_requirement = _build_coder_requirement(task.requirement, review_comments)
        code_draft_output = await run_coder_agent(
            requirement=coder_requirement,
            execution_steps=plan.execution_steps,
            context=context_output,
        )
        task.code_draft = code_draft_output.model_dump_json(indent=2)
        _persist_task(task)

        review_report = await run_reviewer_agent(
            requirement=task.requirement,
            plan=plan,
            code_draft=code_draft_output,
        )
        task.review_report = review_report.model_dump()
        _persist_task(task)

        if review_report.is_passed:
            for snippet in code_draft_output.code_snippets:
                filename = snippet.get("filename", "").strip()
                content = snippet.get("content", "")

                if not filename:
                    logger.error("Task '%s' produced a code snippet without filename.", task.task_id)
                    raise ValueError("Generated code snippet is missing filename.")

                try:
                    target_path = safe_resolve_workspace_path(filename)
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(content, encoding="utf-8")
                    logger.info("Task '%s' wrote generated code to '%s'.", task.task_id, target_path)
                except Exception:
                    logger.exception(
                        "Task '%s' failed to write generated code to '%s'.",
                        task.task_id,
                        filename,
                    )
                    raise

            task.status = TaskStatus.COMPLETED
            _persist_task(task)
            return

        review_comments = review_report.comments
        logger.warning(
            "Task '%s' review failed on attempt %s/%s.",
            task.task_id,
            attempt,
            MAX_REVIEW_RETRIES,
        )

    task.status = TaskStatus.FAILED
    if task.review_report is None:
        task.review_report = {
            "is_passed": False,
            "issues_found": 1,
            "comments": ["Task failed because review did not pass."],
        }
    else:
        comments = list(task.review_report.get("comments", []))
        comments.append(f"Task failed after {MAX_REVIEW_RETRIES} review attempts.")
        task.review_report["comments"] = comments
    _persist_task(task)


async def process_task_pipeline(task_id: str) -> None:
    """根据任务当前状态推进工作流。"""

    task = _get_task(task_id)
    if task is None:
        logger.warning("Task '%s' not found when starting workflow.", task_id)
        return

    try:
        if task.status == TaskStatus.PLANNING:
            await _run_planning_stage(task)
            return

        if task.status == TaskStatus.PROCESSING:
            await _run_processing_stage(task)
            return

        logger.info(
            "Skip task '%s' because its current status is '%s'.",
            task_id,
            task.status,
        )
    except Exception as exc:
        _mark_task_failed(task, f"Workflow pipeline error: {exc}")
