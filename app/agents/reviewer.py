"""代码审查 Agent，实现结构化审查报告输出。"""

from __future__ import annotations

from app.agents.utils import format_execution_steps, format_file_payloads, format_path_list
from app.core.llm_client import generate_structured_response
from app.models.schemas import CodeDraftOutput, PlannerOutput, ReviewReport

REVIEWER_SYSTEM_PROMPT = (
    "你是一个极其严格的审查员。"
    "请对代码进行深度静态分析和逻辑审查。"
    "如果现有实现信息不足，你可以调用工具检查 workspace 文件、查看目录结构或执行受限 shell 命令辅助审查。"
    "仅在审查判断需要更多证据时调用工具。"
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
        "请根据原始需求和执行计划审查以下实现。\n\n"
        f"需求：\n{requirement}\n\n"
        "Planner 的思考过程：\n"
        f"{plan.thinking_process}\n\n"
        "执行步骤：\n"
        f"{format_execution_steps(plan.execution_steps)}\n\n"
        "计划中的目标文件：\n"
        f"{format_path_list(plan.target_files)}\n\n"
        "生成的代码片段：\n"
        f"{format_file_payloads(code_draft.code_snippets)}\n\n"
        "请给出是否通过、问题数量，以及具体到代码行级别的审查意见。"
    )

    return await generate_structured_response(
        system_prompt=REVIEWER_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=ReviewReport,
        model=model,
        task_id=task_id,
        enable_tools=True,
    )
