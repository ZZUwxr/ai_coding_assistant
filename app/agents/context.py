"""上下文提取 Agent，实现基于真实文件读取的上下文分析。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.utils import format_execution_steps, format_file_payloads, read_workspace_files
from app.core.llm_client import generate_structured_response
from app.models.schemas import ContextOutput

CONTEXT_SYSTEM_PROMPT = (
    "你是一个代码分析师。"
    "请根据开发计划与现有代码，提取 Coder 需要的前置代码上下文和依赖关系。"
    "如果现有上下文不足，你可以调用工具查看 workspace 中的目录结构、读取文件片段或执行受限 shell 命令。"
    "仅在补充上下文确有必要时调用工具。"
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
        "请结合以下需求与从 workspace 收集到的真实代码文件进行分析。\n\n"
        f"需求：\n{requirement}\n\n"
        "执行步骤：\n"
        f"{format_execution_steps(execution_steps)}\n\n"
        "相关代码与文件状态：\n"
        f"{format_file_payloads(relevant_code)}\n\n"
        "请识别关键依赖、可能需要修改的函数或类、集成约束，以及 Coder 需要重点注意的冲突点。"
    )

    analysis_output = await generate_structured_response(
        system_prompt=CONTEXT_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=ContextAnalysisOutput,
        model=model,
        task_id=task_id,
        enable_tools=True,
    )

    return ContextOutput(
        relevant_code=relevant_code,
        analysis=analysis_output.analysis,
    )
