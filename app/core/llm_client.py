"""带重试机制的 OpenAI 异步客户端封装。"""

from __future__ import annotations

import inspect
import json
import logging
from typing import TypeVar

import httpx
from openai import AsyncOpenAI, PermissionDeniedError
from pydantic import BaseModel
from tenacity import before_sleep_log, retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.tools import AVAILABLE_TOOLS, get_openai_tools_schema
from app.services.pubsub import stream_manager

logger = logging.getLogger(__name__)

settings = get_settings()
client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    http_client=httpx.AsyncClient(trust_env=False),
)

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)
MAX_TOOL_CALL_ROUNDS = 8


def strip_markdown_code_fence(content: str) -> str:
    """清理大模型返回中的 Markdown 代码块包裹，仅保留 JSON 文本。"""

    cleaned_content = content.strip()

    if cleaned_content.startswith("```"):
        lines = cleaned_content.splitlines()
        if lines:
            lines = lines[1:]
        cleaned_content = "\n".join(lines).strip()

    if cleaned_content.endswith("```"):
        lines = cleaned_content.splitlines()
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned_content = "\n".join(lines).strip()

    return cleaned_content


def _build_enforced_system_prompt(
    system_prompt: str,
    response_model: type[ResponseModelT],
) -> str:
    """将 JSON Schema 约束注入系统提示词。"""

    schema_json = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
    return (
        f"{system_prompt.rstrip()}\n\n"
        "重要要求：你必须只输出合法的 JSON。"
        "你输出的 JSON 必须严格符合以下 Schema：\n"
        f"{schema_json}"
    )


def _normalize_model_output_json(
    content: str,
    response_model: type[ResponseModelT],
) -> str:
    """在校验前归一化不同供应商返回的 JSON 包装结构。"""

    try:
        parsed_content = json.loads(content)
    except json.JSONDecodeError:
        return content

    if not isinstance(parsed_content, dict):
        return content

    expected_fields = set(response_model.model_fields)
    if expected_fields & set(parsed_content):
        return content

    properties_payload = parsed_content.get("properties")
    if isinstance(properties_payload, dict) and expected_fields & set(properties_payload):
        return json.dumps(properties_payload, ensure_ascii=False)

    return content


def _build_final_json_prompt() -> str:
    """构造最后一轮提示词，强制模型只输出纯 JSON。"""

    return (
        "现在请只返回最终答案对应的 JSON 对象。"
        "不要再调用工具，不要输出工具计划、工具调用轨迹、Schema 定义或 Markdown。"
    )


async def _stream_json_response(
    selected_model: str,
    messages: list[dict[str, object]],
    task_id: str | None,
) -> str:
    """流式获取普通 JSON 响应，并按需发布到 SSE。"""

    response = await client.chat.completions.create(
        model=selected_model,
        messages=messages,
        response_format={"type": "json_object"},
        stream=True,
    )

    accumulated_parts: list[str] = []

    async for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        token = delta.content if delta else None
        if not token:
            continue

        accumulated_parts.append(token)
        if task_id:
            await stream_manager.publish(task_id, event_type="llm_chunk", data=token)

    content = "".join(accumulated_parts).strip()
    if not content:
        raise ValueError("LLM returned empty content.")

    return content


def _build_tool_history_message_from_content(
    tool_calls: list[dict[str, str]],
) -> dict[str, object]:
    """根据从纯文本中解析出的工具调用，构造 assistant 历史消息。"""

    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tool_call["id"],
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                },
            }
            for tool_call in tool_calls
        ],
    }


def _assistant_message_to_history(message: object) -> dict[str, object]:
    """将 assistant 响应转换为后续轮次可复用的历史消息。"""

    content = getattr(message, "content", None)
    tool_calls = getattr(message, "tool_calls", None) or []

    history_message: dict[str, object] = {
        "role": "assistant",
        "content": content,
    }
    if tool_calls:
        history_message["tool_calls"] = [
            tool_call.model_dump(exclude_none=True)
            for tool_call in tool_calls
        ]
    return history_message


def _extract_tool_calls_from_content(content: str | None) -> list[dict[str, str]] | None:
    """识别被供应商塞进 message.content 里的工具调用载荷。"""

    if not content:
        return None

    try:
        parsed_content = json.loads(content)
    except json.JSONDecodeError:
        return None

    candidates: object = parsed_content
    if isinstance(parsed_content, dict) and "tool_calls" in parsed_content:
        candidates = parsed_content["tool_calls"]

    if isinstance(candidates, dict):
        candidates = [candidates]

    if not isinstance(candidates, list):
        return None

    normalized_calls: list[dict[str, str]] = []
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            return None

        tool_name = candidate.get("name")
        raw_arguments = candidate.get("arguments", "{}")
        if not isinstance(tool_name, str) or tool_name not in AVAILABLE_TOOLS:
            return None

        if isinstance(raw_arguments, dict):
            arguments_json = json.dumps(raw_arguments, ensure_ascii=False)
        elif isinstance(raw_arguments, str):
            arguments_json = raw_arguments
        else:
            return None

        normalized_calls.append(
            {
                "id": f"content_tool_call_{index}",
                "name": tool_name,
                "arguments": arguments_json,
            }
        )

    return normalized_calls or None


def _parse_tool_arguments(arguments_json: str | None) -> dict[str, object]:
    """将原始 JSON 工具参数解析为字典。"""

    if not arguments_json:
        return {}

    try:
        parsed_arguments = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"工具参数 JSON 不合法：{exc}") from exc

    if not isinstance(parsed_arguments, dict):
        raise ValueError("工具参数解析后必须是 JSON 对象。")

    return parsed_arguments


async def _execute_tool_call(tool_call: object) -> dict[str, str]:
    """执行单个工具调用，并返回下一轮模型所需的 tool 消息。"""

    if isinstance(tool_call, dict):
        tool_name = tool_call.get("name")
        raw_arguments = tool_call.get("arguments")
        tool_call_id = str(tool_call.get("id", ""))
    else:
        function_payload = getattr(tool_call, "function", None)
        tool_name = getattr(function_payload, "name", None)
        raw_arguments = getattr(function_payload, "arguments", None)
        tool_call_id = getattr(tool_call, "id", "")

    if not tool_name:
        tool_output = "错误：工具调用缺少函数名。"
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": tool_output,
        }

    try:
        tool_function = AVAILABLE_TOOLS[tool_name]
    except KeyError:
        tool_output = (
            f"错误：未知工具 '{tool_name}'。"
            f"当前可用工具有：{', '.join(sorted(AVAILABLE_TOOLS))}。"
        )
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": tool_output,
        }

    try:
        parsed_arguments = _parse_tool_arguments(raw_arguments)
        tool_result = tool_function(**parsed_arguments)
        if inspect.isawaitable(tool_result):
            tool_result = await tool_result
        tool_output = str(tool_result)
    except Exception as exc:
        logger.warning("Tool '%s' execution failed: %s", tool_name, exc)
        tool_output = (
            f"错误：工具 '{tool_name}' 执行失败，异常类型为 {type(exc).__name__}：{exc}。"
            f"参数：{raw_arguments or '{}'}"
        )

    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": tool_output,
    }


async def _generate_response_with_tools(
    selected_model: str,
    messages: list[dict[str, object]],
    task_id: str | None,
) -> str:
    """先执行工具调用循环，再单独请求最终的严格 JSON 输出。"""

    for _ in range(MAX_TOOL_CALL_ROUNDS):
        response = await client.chat.completions.create(
            model=selected_model,
            messages=messages,
            tools=get_openai_tools_schema(),
        )
        if not response.choices:
            raise ValueError("LLM returned no choices.")

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            content_tool_calls = _extract_tool_calls_from_content(message.content)
            if content_tool_calls:
                messages.append(_build_tool_history_message_from_content(content_tool_calls))
                for tool_call in content_tool_calls:
                    tool_result_message = await _execute_tool_call(tool_call)
                    messages.append(tool_result_message)
                continue

        if not tool_calls:
            content = (message.content or "").strip()
            if content:
                messages.append({"role": "assistant", "content": content})
            break

        messages.append(_assistant_message_to_history(message))
        for tool_call in tool_calls:
            tool_result_message = await _execute_tool_call(tool_call)
            messages.append(tool_result_message)
    else:
        raise ValueError(
            f"LLM exceeded the maximum number of tool-calling rounds ({MAX_TOOL_CALL_ROUNDS})."
        )

    final_messages = messages + [
        {
            "role": "user",
            "content": _build_final_json_prompt(),
        }
    ]
    return await _stream_json_response(
        selected_model=selected_model,
        messages=final_messages,
        task_id=task_id,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type((PermissionDeniedError,)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def generate_structured_response(
    system_prompt: str,
    user_message: str,
    response_model: type[ResponseModelT],
    model: str | None = None,
    task_id: str | None = None,
    enable_tools: bool = False,
) -> ResponseModelT:
    """调用大模型并将结果强制解析为指定的 Pydantic 模型。"""

    selected_model = model or settings.openai_model
    enforced_system_prompt = _build_enforced_system_prompt(system_prompt, response_model)
    messages: list[dict[str, object]] = [
        {"role": "system", "content": enforced_system_prompt},
        {"role": "user", "content": user_message},
    ]

    try:
        if enable_tools:
            content = await _generate_response_with_tools(
                selected_model=selected_model,
                messages=messages,
                task_id=task_id,
            )
        else:
            content = await _stream_json_response(
                selected_model=selected_model,
                messages=messages,
                task_id=task_id,
            )
    except Exception:
        logger.exception(
            "LLM request failed for model '%s' with response model '%s'.",
            selected_model,
            response_model.__name__,
        )
        raise

    try:
        cleaned_content = strip_markdown_code_fence(content)
        normalized_content = _normalize_model_output_json(cleaned_content, response_model)
        return response_model.model_validate_json(normalized_content)
    except Exception:
        logger.exception(
            "Failed to validate structured response for model '%s' and schema '%s'.",
            selected_model,
            response_model.__name__,
        )
        raise
