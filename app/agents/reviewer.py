"""代码审查 Agent，实现结构化审查报告输出。"""

from __future__ import annotations

from app.agents.utils import format_execution_steps, format_file_payloads, format_path_list
from app.core.llm_client import generate_structured_response
from app.models.schemas import CodeDraftOutput, PlannerOutput, ReviewReport

REVIEWER_SYSTEM_PROMPT = (
    "你是一个极其严格的审查员。"
    "请对代码进行深度静态分析和逻辑审查。"
    "必须明确指出是否通过、发现的缺陷数量，并给出具体的代码行级修改建议。"
)


async def run_reviewer_agent(
    requirement: str,
    plan: PlannerOutput,
    code_draft: CodeDraftOutput,
    model: str | None = None,
    task_id: str | None = None,
) -> ReviewReport:
    """根据需求、计划和代码实现生成结构化审查报告。"""

    user_message = (
        "Review the following implementation against the original requirement and plan.\n\n"
        f"Requirement:\n{requirement}\n\n"
        "Planner thinking process:\n"
        f"{plan.thinking_process}\n\n"
        "Execution steps:\n"
        f"{format_execution_steps(plan.execution_steps)}\n\n"
        "Planned target files:\n"
        f"{format_path_list(plan.target_files)}\n\n"
        "Generated code snippets:\n"
        f"{format_file_payloads(code_draft.code_snippets)}\n\n"
        "Provide pass or fail, issue count, and concrete line-level review comments."
    )

    return await generate_structured_response(
        system_prompt=REVIEWER_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=ReviewReport,
        model=model,
        task_id=task_id,
    )
