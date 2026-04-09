"""Agent 工具注册表与 OpenAI Tools Schema 定义。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import get_settings

COMMAND_TIMEOUT_SECONDS = 15
MAX_TOOL_OUTPUT_CHARS = 12_000


def _get_workspace_dir() -> Path:
    """返回解析后的工作区目录，并确保目录存在。"""

    workspace_dir = get_settings().workspace_dir
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir.resolve()


def _resolve_workspace_path(path: str) -> Path:
    """将相对路径安全解析到工作区内，并阻止路径穿越。"""

    normalized_path = path.strip().replace("\\", "/")
    if not normalized_path:
        raise ValueError("路径不能为空。")

    raw_path = Path(normalized_path)
    if raw_path.is_absolute():
        raise ValueError("不允许使用绝对路径。")

    workspace_dir = _get_workspace_dir()
    resolved_path = (workspace_dir / raw_path).resolve()

    try:
        resolved_path.relative_to(workspace_dir)
    except ValueError as exc:
        raise ValueError("路径越界，超出了工作区目录。") from exc

    return resolved_path


def _truncate_tool_output(content: str) -> str:
    """限制工具输出长度，避免返回内容过长影响提示词。"""

    if len(content) <= MAX_TOOL_OUTPUT_CHARS:
        return content

    return f"{content[:MAX_TOOL_OUTPUT_CHARS]}\n... [内容已截断]"


def list_directory(path: str) -> str:
    """列出工作区相对目录下的文件和子目录。"""

    target_path = _resolve_workspace_path(path)
    if not target_path.exists():
        raise FileNotFoundError(f"目录不存在：{path}")
    if not target_path.is_dir():
        raise ValueError(f"目标路径不是目录：{path}")

    entries = sorted(target_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    if not entries:
        return f"目录 '{path}' 为空。"

    lines = [f"目录 '{path}' 的内容如下："]
    for entry in entries:
        marker = "[目录]" if entry.is_dir() else "[文件]"
        lines.append(f"{marker} {entry.name}")

    return _truncate_tool_output("\n".join(lines))


def read_file_content(file_path: str, start_line: int = 1, end_line: int = -1) -> str:
    """读取工作区相对文件内容，并可按行号范围截取。"""

    if start_line < 1:
        raise ValueError("start_line 必须大于或等于 1。")
    if end_line != -1 and end_line < start_line:
        raise ValueError("end_line 必须为 -1，或大于等于 start_line。")

    target_path = _resolve_workspace_path(file_path)
    if not target_path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")
    if not target_path.is_file():
        raise ValueError(f"目标路径不是文件：{file_path}")

    content = target_path.read_text(encoding="utf-8", errors="ignore")
    if not content:
        return f"文件 '{file_path}' 为空。"

    lines = content.splitlines()
    total_lines = len(lines)
    if start_line > total_lines:
        raise ValueError(
            f"start_line={start_line} 超出了文件 '{file_path}' 的总行数 {total_lines}。"
        )

    effective_end_line = total_lines if end_line == -1 else min(end_line, total_lines)
    selected_lines = lines[start_line - 1 : effective_end_line]

    numbered_lines = [
        f"{line_number}: {line}"
        for line_number, line in enumerate(selected_lines, start=start_line)
    ]
    result = (
        f"文件：{file_path}\n"
        f"显示第 {start_line}-{effective_end_line} 行，总计 {total_lines} 行\n"
        + "\n".join(numbered_lines)
    )
    return _truncate_tool_output(result)


async def run_shell_command(command: str) -> str:
    """在工作区内执行 shell 命令，并限制 15 秒超时。"""

    normalized_command = command.strip()
    if not normalized_command:
        raise ValueError("command 不能为空。")

    workspace_dir = _get_workspace_dir()
    process = await asyncio.create_subprocess_shell(
        normalized_command,
        cwd=str(workspace_dir),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        timed_out = True
        process.kill()
        stdout, stderr = await process.communicate()

    stdout_text = stdout.decode("utf-8", errors="ignore").strip()
    stderr_text = stderr.decode("utf-8", errors="ignore").strip()

    sections = [
        f"命令：{normalized_command}",
        f"工作目录：{workspace_dir}",
        f"退出码：{process.returncode}",
    ]
    if timed_out:
        sections.append(f"命令执行超时，超过 {COMMAND_TIMEOUT_SECONDS} 秒。")
    if stdout_text:
        sections.append(f"标准输出：\n{stdout_text}")
    if stderr_text:
        sections.append(f"标准错误：\n{stderr_text}")
    if not stdout_text and not stderr_text:
        sections.append("命令没有产生任何输出。")

    return _truncate_tool_output("\n\n".join(sections))


AVAILABLE_TOOLS: dict[str, Callable[..., Any]] = {
    "list_directory": list_directory,
    "read_file_content": read_file_content,
    "run_shell_command": run_shell_command,
}


def get_openai_tools_schema() -> list[dict[str, Any]]:
    """返回注册工具对应的 OpenAI Tools Schema。"""

    return [
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": (
                    "列出工作区根目录下某个相对目录中的文件和子目录。"
                    "如果要查看工作区根目录本身，可传入 '.'。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "相对于工作区根目录的目录路径。",
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_content",
                "description": (
                    "读取工作区根目录下某个相对文件的内容。"
                    "可选地指定起止行号。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "相对于工作区根目录的文件路径。",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "起始行号，1-based，包含该行。",
                            "default": 1,
                            "minimum": 1,
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "结束行号，1-based，包含该行。传 -1 表示读取到文件末尾。",
                            "default": -1,
                        },
                    },
                    "required": ["file_path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_shell_command",
                "description": (
                    "在工作区目录中执行一条 shell 命令。"
                    "该命令会受到 15 秒超时限制。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "在工作区根目录中执行的 shell 命令。",
                        }
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        },
    ]
