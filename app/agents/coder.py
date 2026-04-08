"""代码生成 Agent，实现基于真实上下文的代码输出。"""

from __future__ import annotations

from app.agents.utils import format_execution_steps, format_file_payloads
from app.core.llm_client import generate_structured_response
from app.models.schemas import CodeDraftOutput, ContextOutput

CODER_SYSTEM_PROMPT = (
    "你是一个全栈工程师。"
    "请严格遵循执行计划和上下文，编写生产级别的完整代码。"
    "返回的每个代码对象都必须包含 filename 和 content，content 必须是完整文件内容。"
)


async def run_coder_agent(
    requirement: str,
    execution_steps: list[str],
    context: ContextOutput,
    model: str | None = None,
) -> CodeDraftOutput:
    """根据需求、计划和真实上下文生成完整代码文件内容。"""

    user_message = (
        "Implement the following requirement with complete runnable file contents.\n\n"
        f"Requirement:\n{requirement}\n\n"
        "Execution steps:\n"
        f"{format_execution_steps(execution_steps)}\n\n"
        "Existing relevant code from the workspace:\n"
        f"{format_file_payloads(context.relevant_code)}\n\n"
        "Context analysis:\n"
        f"{context.analysis}\n\n"
        "Return the final implementation as code_snippets. Each item must include filename and content."
    )

    return await generate_structured_response(
        system_prompt=CODER_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=CodeDraftOutput,
        model=model,
    )
