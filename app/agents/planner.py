"""需求拆解 Agent，实现结构化计划生成。"""

from __future__ import annotations

from app.agents.utils import format_path_list
from app.core.llm_client import generate_structured_response
from app.models.schemas import PlannerOutput

PLANNER_SYSTEM_PROMPT = (
    "你是一个资深的软件架构师。"
    "你的职责是将模糊的研发需求拆解为结构化的执行计划。"
    "必须包含思考过程、具体执行步骤和目标文件列表。"
    "target_files 必须使用相对于 workspace 根目录的文件路径。"
)


async def run_planner_agent(
    requirement: str,
    context_files: list[str] | None = None,
    model: str | None = None,
    task_id: str | None = None,
) -> PlannerOutput:
    """根据研发需求生成结构化执行计划。"""

    user_message = (
        "Analyze the following software development requirement and produce a structured plan.\n\n"
        f"Requirement:\n{requirement}\n\n"
        "Known context files in the workspace:\n"
        f"{format_path_list(context_files)}\n\n"
        "Return practical execution steps and file paths that should be edited or created."
    )

    return await generate_structured_response(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=PlannerOutput,
        model=model,
        task_id=task_id,
    )
