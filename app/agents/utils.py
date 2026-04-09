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
        raise ValueError("目标文件路径不能为空。")

    raw_path = Path(normalized_path)
    if raw_path.is_absolute():
        raise ValueError("不允许使用绝对路径。")

    workspace_dir = get_workspace_dir()
    resolved_path = (workspace_dir / raw_path).resolve()

    try:
        resolved_path.relative_to(workspace_dir)
    except ValueError as exc:
        raise ValueError("路径越界，超出了工作区目录。") from exc

    return resolved_path


async def read_workspace_file(relative_path: str, max_chars: int = MAX_FILE_CHARS) -> dict[str, str]:
    """读取工作区内文件内容，不存在的文件以占位说明返回。"""

    try:
        resolved_path = safe_resolve_workspace_path(relative_path)
    except ValueError as exc:
        logger.warning("Rejected unsafe workspace path '%s': %s", relative_path, exc)
        return {"filename": relative_path, "content": f"路径被拒绝：{exc}"}

    if not resolved_path.exists():
        return {
            "filename": relative_path,
            "content": "新文件：该文件在 workspace 中尚不存在。",
        }

    if not resolved_path.is_file():
        return {
            "filename": relative_path,
            "content": "路径无效：目标路径存在，但不是普通文件。",
        }

    content = await asyncio.to_thread(
        resolved_path.read_text,
        encoding="utf-8",
        errors="ignore",
    )

    if len(content) > max_chars:
        content = f"{content[:max_chars]}\n... [内容已截断]"

    if not content:
        content = "# 空文件"

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
        return "1. 无"

    return "\n".join(f"{index}. {step}" for index, step in enumerate(execution_steps, start=1))


def format_path_list(paths: list[str] | None) -> str:
    """将文件路径列表格式化为项目符号列表。"""

    if not paths:
        return "- 无"

    return "\n".join(f"- {path}" for path in paths)


def format_file_payloads(file_payloads: list[dict[str, str]]) -> str:
    """将文件内容列表格式化为适合放入 Prompt 的文本块。"""

    if not file_payloads:
        return "未提供相关文件。"

    blocks: list[str] = []
    for payload in file_payloads:
        filename = payload.get("filename", "未知文件")
        content = payload.get("content", "")
        blocks.append(f"文件：{filename}\n```text\n{content}\n```")

    return "\n\n".join(blocks)
