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
        "请分析以下软件开发需求，并输出结构化执行计划。\n\n"
        f"需求：\n{requirement}\n\n"
        "workspace 中已知的上下文文件：\n"
        f"{format_path_list(context_files)}\n\n"
        "请返回可执行的步骤，以及需要编辑或创建的文件路径。"
    )

    return await generate_structured_response(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=PlannerOutput,
        model=model,
        task_id=task_id,
    )
