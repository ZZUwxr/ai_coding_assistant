"""基于 Typer + Rich 的 AI Coding Assistant 交互式 CLI 客户端。"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

TASK_API_PREFIX = "/api/v1/tasks"
CREATE_TASK_ENDPOINT = f"{TASK_API_PREFIX}/"
STREAM_TASK_ENDPOINT = f"{TASK_API_PREFIX}/{{task_id}}/stream"
TERMINAL_STATUSES = {"COMPLETED", "FAILED"}

DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_PLANNING_TIMEOUT = 180
DEFAULT_FINAL_TIMEOUT = 480
DEFAULT_POLL_INTERVAL = 2.0

console = Console()


class CliError(RuntimeError):
    """CLI 可读错误，用于统一提示与退出码处理。"""


class TaskStreamPrinter:
    """后台消费 SSE 流并实时打印模型输出。"""

    def __init__(self, base_url: str, task_id: str) -> None:
        self.base_url = base_url
        self.task_id = task_id
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._header_printed = False
        self._has_open_token_line = False
        self._last_llm_char: str | None = None

    def start(self) -> None:
        """启动后台流式打印线程。"""

        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(target=self._run, name=f"sse-printer-{self.task_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止后台线程。"""

        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

        if self._has_open_token_line:
            console.print()
            self._has_open_token_line = False

    def _run(self) -> None:
        """消费 SSE 流并分发事件。"""

        endpoint = STREAM_TASK_ENDPOINT.format(task_id=self.task_id)
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0)

        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=timeout,
                follow_redirects=True,
                trust_env=False,
            ) as client:
                with client.stream("GET", endpoint) as response:
                    if response.is_error:
                        detail = _extract_error_detail(response)
                        console.print(f"[yellow]SSE 连接失败: {detail}[/yellow]")
                        return

                    event_type = "message"
                    data_lines: list[str] = []

                    for raw_line in response.iter_lines():
                        if self._stop_event.is_set():
                            return

                        line = raw_line.strip("\r")

                        if not line:
                            self._dispatch_event(event_type, "\n".join(data_lines))
                            event_type = "message"
                            data_lines = []
                            continue

                        if line.startswith("event:"):
                            event_type = line.split(":", maxsplit=1)[1].strip()
                            continue

                        if line.startswith("data:"):
                            data_part = line.split(":", maxsplit=1)[1]
                            if data_part.startswith(" "):
                                data_part = data_part[1:]
                            data_lines.append(data_part)

                    if data_lines:
                        self._dispatch_event(event_type, "\n".join(data_lines))
        except Exception as exc:
            if not self._stop_event.is_set():
                console.print(f"[yellow]SSE 实时输出中断：{exc}[/yellow]")

    def _dispatch_event(self, event_type: str, payload: str) -> None:
        """按事件类型进行终端展示。"""

        if not payload:
            return

        if event_type == "llm_chunk":
            if not self._header_printed:
                console.print("\n[bold cyan]实时模型输出[/bold cyan]")
                self._header_printed = True

            # 不同阶段的 JSON 结果可能无分隔符直接相连（例如 `}{`），
            # 这里做一个轻量换行处理，提升可读性。
            if payload and payload[0] in "{[" and self._last_llm_char in {"}", "]"}:
                console.print()

            console.print(payload, end="", markup=False, highlight=False, soft_wrap=True)
            self._has_open_token_line = True
            self._last_llm_char = payload[-1]
            return

        if event_type == "status_update":
            if self._has_open_token_line:
                console.print()
                self._has_open_token_line = False
            console.print(f"[dim]状态更新: {payload}[/dim]")
            if payload in TERMINAL_STATUSES:
                self._stop_event.set()


def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
    """安全读取 JSON；解析失败时返回 None。"""

    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _extract_error_detail(response: httpx.Response) -> str:
    """从失败响应中提取可读错误信息。"""

    payload = _safe_json(response)
    if payload is not None:
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return str(payload)

    raw_text = response.text.strip()
    if raw_text:
        return raw_text
    return "No response detail."


def request_json(
    client: httpx.Client,
    method: str,
    endpoint: str,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """发送请求并返回 JSON 对象；失败时抛出 CliError。"""

    try:
        response = client.request(method=method, url=endpoint, json=json_body)
    except httpx.RequestError as exc:
        raise CliError(
            f"无法连接后端服务 {client.base_url}。请确认服务已启动并检查网络。原始错误: {exc}"
        ) from exc

    if response.is_error:
        detail = _extract_error_detail(response)
        raise CliError(
            f"{method.upper()} {endpoint} 请求失败 (HTTP {response.status_code})：{detail}"
        )

    payload = _safe_json(response)
    if payload is None:
        raise CliError(f"{method.upper()} {endpoint} 返回非 JSON 对象，无法解析。")

    return payload


def create_task(client: httpx.Client, requirement: str) -> dict[str, Any]:
    """创建任务并返回任务详情。"""

    payload = request_json(
        client=client,
        method="POST",
        endpoint=CREATE_TASK_ENDPOINT,
        json_body={"requirement": requirement},
    )

    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise CliError("创建任务成功但响应缺少有效 task_id。")

    return payload


def get_task(client: httpx.Client, task_id: str) -> dict[str, Any]:
    """查询任务详情。"""

    payload = request_json(
        client=client,
        method="GET",
        endpoint=f"{TASK_API_PREFIX}/{task_id}",
    )
    status = payload.get("status")
    if not isinstance(status, str) or not status.strip():
        raise CliError("任务查询返回缺少有效 status 字段。")

    return payload


def approve_task(
    client: httpx.Client,
    task_id: str,
    is_approved: bool,
    feedback: str | None = None,
) -> dict[str, Any]:
    """提交人工审批结果。"""

    payload: dict[str, Any] = {"is_approved": is_approved}
    if feedback is not None:
        payload["feedback"] = feedback

    return request_json(
        client=client,
        method="POST",
        endpoint=f"{TASK_API_PREFIX}/{task_id}/approve",
        json_body=payload,
    )


def wait_for_status(
    client: httpx.Client,
    task_id: str,
    target_statuses: set[str],
    timeout_seconds: int,
    poll_interval: float,
    spinner_text: str,
    use_spinner: bool = True,
) -> dict[str, Any]:
    """轮询任务状态，直到进入目标状态或超时。"""

    started_at = time.perf_counter()
    if use_spinner:
        with console.status(spinner_text, spinner="dots"):
            while True:
                task = get_task(client, task_id)
                current_status = str(task.get("status"))
                if current_status in target_statuses:
                    return task

                elapsed = time.perf_counter() - started_at
                if elapsed >= timeout_seconds:
                    raise CliError(
                        f"等待任务进入 {sorted(target_statuses)} 超时 ({timeout_seconds}s)。"
                        f"当前状态: {current_status}"
                    )

                time.sleep(poll_interval)

    console.print(f"[dim]{spinner_text}[/dim]")
    while True:
        task = get_task(client, task_id)
        current_status = str(task.get("status"))
        if current_status in target_statuses:
            return task

        elapsed = time.perf_counter() - started_at
        if elapsed >= timeout_seconds:
            raise CliError(
                f"等待任务进入 {sorted(target_statuses)} 超时 ({timeout_seconds}s)。"
                f"当前状态: {current_status}"
            )

        time.sleep(poll_interval)


def render_welcome(base_url: str) -> None:
    """渲染 CLI 欢迎界面。"""

    ascii_art = r"""
    ___    ____      ____          ___
   /   |  /  _/     / __ \____ ___/ (_)___  ____ _
  / /| |  / /______/ / / / __ `/ __  / / __ \/ __ `/
 / ___ |_/ /_____/ /_/ / /_/ / /_/ / / / / / /_/ /
/_/  |_/___/    /_____/\__,_/\__,_/_/_/ /_/\__, /
                                           /____/
"""

    console.print(
        Panel.fit(
            f"[bold cyan]{ascii_art}[/bold cyan]\n"
            "[bold white]AI Coding Assistant Interactive CLI[/bold white]",
            border_style="bright_cyan",
            title="Welcome",
            subtitle="Typer + Rich",
        )
    )
    console.print(f"[dim]Backend: {base_url}[/dim]\n")


def ask_requirement() -> str:
    """读取用户输入的研发需求。"""

    while True:
        requirement = Prompt.ask("请输入自然语言研发需求").strip()
        if requirement:
            return requirement
        console.print("[yellow]需求不能为空，请重新输入。[/yellow]")


def render_plan(task: dict[str, Any]) -> None:
    """展示 Planner 输出内容。"""

    plan = task.get("plan")
    if not isinstance(plan, dict):
        raise CliError("任务已进入审批阶段，但响应中缺少有效 plan。")

    thinking = plan.get("thinking_process")
    thinking_text = thinking.strip() if isinstance(thinking, str) and thinking.strip() else "_未提供思考过程_"

    execution_steps = plan.get("execution_steps")
    parsed_steps: list[str] = []
    if isinstance(execution_steps, list):
        for item in execution_steps:
            content = item.strip() if isinstance(item, str) else str(item).strip()
            if content:
                parsed_steps.append(content)

    if parsed_steps:
        steps_markdown = "\n".join(f"{index}. {step}" for index, step in enumerate(parsed_steps, start=1))
    else:
        steps_markdown = "1. _未提供执行步骤_"

    markdown_text = (
        "## Planner 思考过程\n\n"
        f"{thinking_text}\n\n"
        "## 执行步骤\n\n"
        f"{steps_markdown}\n"
    )

    console.print(
        Panel(
            Markdown(markdown_text),
            title="规划结果",
            border_style="magenta",
            padding=(1, 2),
        )
    )


def extract_failure_reason(task: dict[str, Any]) -> str:
    """提取任务失败原因。"""

    review_report = task.get("review_report")
    if isinstance(review_report, dict):
        comments = review_report.get("comments")
        if isinstance(comments, list):
            lines = [str(item).strip() for item in comments if str(item).strip()]
            if lines:
                return "\n".join(f"- {line}" for line in lines)

    detail = task.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()

    status = task.get("status")
    if isinstance(status, str) and status.strip():
        return f"任务状态为 {status}，未返回更详细错误信息。"
    return "任务失败，未返回可读错误信息。"


def extract_issues_found(task: dict[str, Any]) -> int | None:
    """提取 Reviewer 检出问题数量。"""

    review_report = task.get("review_report")
    if not isinstance(review_report, dict):
        return None

    issues_found = review_report.get("issues_found")
    if isinstance(issues_found, int):
        return issues_found
    return None


def run_interactive_flow(
    *,
    base_url: str,
    planning_timeout: int,
    final_timeout: int,
    poll_interval: float,
) -> int:
    """执行完整 CLI 交互流程。"""

    render_welcome(base_url)
    requirement = ask_requirement()

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)
    with httpx.Client(
        base_url=base_url,
        timeout=timeout,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        created_task = create_task(client, requirement)
        task_id = str(created_task["task_id"])
        console.print(f"[bold]任务已创建[/bold] task_id=[cyan]{task_id}[/cyan]\n")

        stream_printer = TaskStreamPrinter(base_url=base_url, task_id=task_id)
        stream_printer.start()

        try:
            while True:
                planned_task = wait_for_status(
                    client=client,
                    task_id=task_id,
                    target_statuses={"WAITING_FOR_APPROVAL", "FAILED"},
                    timeout_seconds=planning_timeout,
                    poll_interval=poll_interval,
                    spinner_text="🤖 Planner 正在思考并拆解需求...",
                    use_spinner=False,
                )

                if str(planned_task.get("status")) == "FAILED":
                    console.print("[bold red]❌ 任务失败！[/bold red]")
                    console.print(f"[red]{extract_failure_reason(planned_task)}[/red]")
                    return 1

                render_plan(planned_task)

                if typer.confirm("您是否同意该执行计划？", default=True):
                    approve_task(client=client, task_id=task_id, is_approved=True)
                    console.print("[green]审批已通过，开始进入编码与审查阶段。[/green]\n")
                    break

                feedback = Prompt.ask("请输入您的修改建议").strip()
                if not feedback:
                    feedback = "请结合当前需求重新规划，给出更清晰可执行的步骤。"

                approve_task(
                    client=client,
                    task_id=task_id,
                    is_approved=False,
                    feedback=feedback,
                )
                console.print("[yellow]已提交修改建议，Planner 正在重新规划...[/yellow]\n")

            final_task = wait_for_status(
                client=client,
                task_id=task_id,
                target_statuses=TERMINAL_STATUSES,
                timeout_seconds=final_timeout,
                poll_interval=poll_interval,
                spinner_text="💻 Coder 正在编写代码，Reviewer 正在严格审查...",
                use_spinner=False,
            )
        finally:
            stream_printer.stop()

        if str(final_task.get("status")) == "COMPLETED":
            issues_found = extract_issues_found(final_task)
            issue_text = str(issues_found) if issues_found is not None else "N/A"
            console.print("[bold green]✅ 任务完成！代码已生成并保存至 Workspace。[/bold green]")
            console.print(f"[green]Reviewer 发现的改进点数量：{issue_text}[/green]")
            return 0

        console.print("[bold red]❌ 任务失败！[/bold red]")
        console.print(f"[red]{extract_failure_reason(final_task)}[/red]")
        return 1


def main(
    base_url: str = typer.Option(
        DEFAULT_BASE_URL,
        "--base-url",
        help="FastAPI 服务地址。",
    ),
    planning_timeout: int = typer.Option(
        DEFAULT_PLANNING_TIMEOUT,
        "--planning-timeout",
        help="等待规划进入审批状态的超时时间（秒）。",
    ),
    final_timeout: int = typer.Option(
        DEFAULT_FINAL_TIMEOUT,
        "--final-timeout",
        help="等待任务完成或失败的超时时间（秒）。",
    ),
    poll_interval: float = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        help="轮询任务状态的间隔（秒）。",
    ),
) -> None:
    """启动单入口交互式 CLI。"""

    if planning_timeout <= 0:
        raise typer.BadParameter("--planning-timeout 必须大于 0。")
    if final_timeout <= 0:
        raise typer.BadParameter("--final-timeout 必须大于 0。")
    if poll_interval <= 0:
        raise typer.BadParameter("--poll-interval 必须大于 0。")

    normalized_base_url = base_url.strip().rstrip("/")
    if not normalized_base_url:
        raise typer.BadParameter("--base-url 不能为空。")

    try:
        exit_code = run_interactive_flow(
            base_url=normalized_base_url,
            planning_timeout=planning_timeout,
            final_timeout=final_timeout,
            poll_interval=poll_interval,
        )
    except CliError as exc:
        console.print(f"[bold red]❌ 请求失败：{exc}[/bold red]")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n[yellow]已取消操作。[/yellow]")
        raise typer.Exit(code=130) from None

    if exit_code != 0:
        raise typer.Exit(code=exit_code)


if __name__ == "__main__":
    typer.run(main)
