"""代码生成 Agent，实现基于真实上下文的代码输出。"""

from __future__ import annotations

from app.agents.utils import format_execution_steps, format_file_payloads
from app.core.llm_client import generate_structured_response
from app.models.schemas import CodeDraftOutput, ContextOutput

CODER_SYSTEM_PROMPT = (
    "你是一个全栈工程师。"
    "请严格遵循执行计划和上下文，编写生产级别的完整代码。"
    "当已提供的上下文不足时，你可以调用工具检查 workspace 中的目录、文件内容或执行受限 shell 命令。"
    "只在确有必要时调用工具，并优先复用已给出的上下文信息。"
    "返回的每个代码对象都必须包含 filename 和 content，content 必须是完整文件内容。"
)


async def run_coder_agent(
    requirement: str,
    execution_steps: list[str],
    context: ContextOutput,
    model: str | None = None,
    task_id: str | None = None,
) -> CodeDraftOutput:
    """根据需求、计划和真实上下文生成完整代码文件内容。"""

    user_message = (
        "请根据以下需求实现完整且可运行的文件内容。\n\n"
        f"需求：\n{requirement}\n\n"
        "执行步骤：\n"
        f"{format_execution_steps(execution_steps)}\n\n"
        "workspace 中已有的相关代码：\n"
        f"{format_file_payloads(context.relevant_code)}\n\n"
        "上下文分析：\n"
        f"{context.analysis}\n\n"
        "请以 code_snippets 返回最终实现结果，每一项都必须包含 filename 和 content。"
    )

    return await generate_structured_response(
        system_prompt=CODER_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=CodeDraftOutput,
        model=model,
        task_id=task_id,
        enable_tools=True,
    )
