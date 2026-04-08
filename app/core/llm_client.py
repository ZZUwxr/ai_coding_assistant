"""带重试机制的 OpenAI 异步客户端封装。"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

import httpx
from openai import AsyncOpenAI, PermissionDeniedError
from pydantic import BaseModel
from tenacity import before_sleep_log, retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    http_client=httpx.AsyncClient(trust_env=False),
)

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


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
) -> ResponseModelT:
    """调用大模型并将结果强制解析为指定的 Pydantic 模型。"""

    selected_model = model or settings.openai_model
    schema_json = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
    enforced_system_prompt = (
        f"{system_prompt.rstrip()}\n\n"
        "IMPORTANT: You MUST output ONLY valid JSON. "
        "Your output JSON must strictly match the following schema:\n"
        f"{schema_json}"
    )

    try:
        response = await client.chat.completions.create(
            model=selected_model,
            messages=[
                {"role": "system", "content": enforced_system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
        )
    except Exception:
        logger.exception(
            "LLM request failed for model '%s' with response model '%s'.",
            selected_model,
            response_model.__name__,
        )
        raise

    try:
        if not response.choices:
            raise ValueError("LLM returned no choices.")

        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty content.")

        return response_model.model_validate_json(content)
    except Exception:
        logger.exception(
            "Failed to validate structured response for model '%s' and schema '%s'.",
            selected_model,
            response_model.__name__,
        )
        raise
