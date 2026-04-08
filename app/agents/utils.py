"""Agent 共用的安全路径与文件读取工具。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_FILE_CHARS = 12_000


def get_workspace_dir() -> Path:
    """返回工作区根目录，并确保目录存在。"""

    workspace_dir = get_settings().workspace_dir
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir.resolve()


def safe_resolve_workspace_path(relative_path: str) -> Path:
    """将相对路径安全地解析到工作区内，阻止路径穿越。"""

    normalized_path = relative_path.strip().replace("\\", "/")
    if not normalized_path:
        raise ValueError("Target file path is empty.")

    raw_path = Path(normalized_path)
    if raw_path.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    workspace_dir = get_workspace_dir()
    resolved_path = (workspace_dir / raw_path).resolve()

    try:
        resolved_path.relative_to(workspace_dir)
    except ValueError as exc:
        raise ValueError("Path escapes the workspace directory.") from exc

    return resolved_path


async def read_workspace_file(relative_path: str, max_chars: int = MAX_FILE_CHARS) -> dict[str, str]:
    """读取工作区内文件内容，不存在的文件以占位说明返回。"""

    try:
        resolved_path = safe_resolve_workspace_path(relative_path)
    except ValueError as exc:
        logger.warning("Rejected unsafe workspace path '%s': %s", relative_path, exc)
        return {"filename": relative_path, "content": f"PATH_REJECTED: {exc}"}

    if not resolved_path.exists():
        return {
            "filename": relative_path,
            "content": "NEW_FILE: This file does not exist in the workspace yet.",
        }

    if not resolved_path.is_file():
        return {
            "filename": relative_path,
            "content": "PATH_INVALID: The target path exists but is not a regular file.",
        }

    content = await asyncio.to_thread(
        resolved_path.read_text,
        encoding="utf-8",
        errors="ignore",
    )

    if len(content) > max_chars:
        content = f"{content[:max_chars]}\n... [TRUNCATED]"

    if not content:
        content = "# Empty file"

    return {"filename": relative_path, "content": content}


async def read_workspace_files(target_files: list[str]) -> list[dict[str, str]]:
    """并发读取多个工作区文件，并去重保留原始顺序。"""

    deduplicated_paths: list[str] = []
    seen_paths: set[str] = set()

    for target_file in target_files:
        normalized_path = target_file.strip()
        if not normalized_path or normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        deduplicated_paths.append(normalized_path)

    if not deduplicated_paths:
        return []

    return list(await asyncio.gather(*(read_workspace_file(path) for path in deduplicated_paths)))


def format_execution_steps(execution_steps: list[str]) -> str:
    """将执行步骤格式化为编号列表。"""

    if not execution_steps:
        return "1. None"

    return "\n".join(f"{index}. {step}" for index, step in enumerate(execution_steps, start=1))


def format_path_list(paths: list[str] | None) -> str:
    """将文件路径列表格式化为项目符号列表。"""

    if not paths:
        return "- None"

    return "\n".join(f"- {path}" for path in paths)


def format_file_payloads(file_payloads: list[dict[str, str]]) -> str:
    """将文件内容列表格式化为适合放入 Prompt 的文本块。"""

    if not file_payloads:
        return "No relevant files were provided."

    blocks: list[str] = []
    for payload in file_payloads:
        filename = payload.get("filename", "unknown")
        content = payload.get("content", "")
        blocks.append(f"File: {filename}\n```text\n{content}\n```")

    return "\n\n".join(blocks)
