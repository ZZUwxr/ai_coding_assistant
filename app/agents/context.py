"""上下文提取 Agent，实现基于真实文件读取的上下文分析。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.utils import format_execution_steps, format_file_payloads, read_workspace_files
from app.core.llm_client import generate_structured_response
from app.models.schemas import ContextOutput

CONTEXT_SYSTEM_PROMPT = (
    "你是一个代码分析师。"
    "请根据开发计划与现有代码，提取 Coder 需要的前置代码上下文和依赖关系。"
    "不要生成解决当前需求的具体代码。"
)


class ContextAnalysisOutput(BaseModel):
    """Context Agent 内部使用的分析结果模型。"""

    model_config = ConfigDict(extra="forbid")

    analysis: str = Field(..., description="对现有代码上下文、依赖和风险点的分析。")


async def run_context_agent(
    requirement: str,
    execution_steps: list[str],
    target_files: list[str],
    model: str | None = None,
    task_id: str | None = None,
) -> ContextOutput:
    """读取目标文件真实内容，并生成给 Coder 使用的上下文分析。"""

    relevant_code = await read_workspace_files(target_files)
    user_message = (
        "Analyze the following requirement and the real code files collected from the workspace.\n\n"
        f"Requirement:\n{requirement}\n\n"
        "Execution steps:\n"
        f"{format_execution_steps(execution_steps)}\n\n"
        "Relevant code and file states:\n"
        f"{format_file_payloads(relevant_code)}\n\n"
        "Identify key dependencies, likely function or class touch points, integration constraints, "
        "and conflicts the Coder should pay attention to."
    )

    analysis_output = await generate_structured_response(
        system_prompt=CONTEXT_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=ContextAnalysisOutput,
        model=model,
        task_id=task_id,
    )

    return ContextOutput(
        relevant_code=relevant_code,
        analysis=analysis_output.analysis,
    )
