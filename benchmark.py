"""通过真实 HTTP API 驱动 Multi-Agent AI Coding 助手的自动化基准脚本。"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:8000"
TASK_API_PREFIX = "/api/v1/tasks"
CREATE_TASK_ENDPOINT = f"{TASK_API_PREFIX}/"
POLL_INTERVAL_SECONDS = 2
PLANNING_TIMEOUT_SECONDS = 180
FINAL_TIMEOUT_SECONDS = 480
TOTAL_ROUNDS = 2

TASK_PROMPTS = [
    "写一个python脚本，实现输入两个数字，返回他们的和，文件命名为 sum.py"
]


@dataclass
class BenchmarkResult:
    """保存单个测试任务的执行结果。"""

    case_index: int
    prompt: str
    task_id: str
    status: str
    duration_seconds: float
    issues_found: int | None


async def wait_for_status(
    client: httpx.AsyncClient,
    task_id: str,
    target_statuses: set[str],
    timeout_seconds: int,
    progress_message: str,
) -> dict[str, Any]:
    """轮询任务状态，直到进入目标状态或超时。"""

    start = time.perf_counter()
    last_status: str | None = None

    while True:
        response = await client.get(f"{TASK_API_PREFIX}/{task_id}")
        response.raise_for_status()
        task = response.json()
        current_status = task["status"]

        if current_status != last_status:
            print(progress_message.format(status=current_status))
            last_status = current_status

        if current_status in target_statuses:
            return task

        elapsed = time.perf_counter() - start
        if elapsed >= timeout_seconds:
            raise TimeoutError(
                f"Task '{task_id}' timed out after {timeout_seconds}s while waiting for {sorted(target_statuses)}. "
                f"Last status: {current_status}"
            )

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def run_single_case(
    client: httpx.AsyncClient,
    case_index: int,
    total_cases: int,
    prompt: str,
) -> BenchmarkResult:
    """执行单个任务的完整生命周期。"""

    print(f"\n========== 任务 {case_index}/{total_cases} 开始 ==========")
    print(f"需求内容: {prompt}")

    started_at = time.perf_counter()

    create_response = await client.post(
        CREATE_TASK_ENDPOINT,
        json={"requirement": prompt},
    )
    create_response.raise_for_status()
    created_task = create_response.json()
    task_id = created_task["task_id"]
    print(f"任务 {case_index}/{total_cases} 已创建，task_id={task_id}，当前状态={created_task['status']}")

    task = await wait_for_status(
        client=client,
        task_id=task_id,
        target_statuses={"WAITING_FOR_APPROVAL", "FAILED"},
        timeout_seconds=PLANNING_TIMEOUT_SECONDS,
        progress_message=f"任务 {case_index}/{total_cases} 规划阶段状态更新: {{status}}",
    )

    if task["status"] == "FAILED":
        duration_seconds = time.perf_counter() - started_at
        print(f"任务 {case_index}/{total_cases} 在规划阶段失败，耗时 {duration_seconds:.2f}s")
        review_report = task.get("review_report") or {}
        issues_found = review_report.get("issues_found")
        return BenchmarkResult(
            case_index=case_index,
            prompt=prompt,
            task_id=task_id,
            status=task["status"],
            duration_seconds=duration_seconds,
            issues_found=issues_found if isinstance(issues_found, int) else None,
        )

    print(f"任务 {case_index}/{total_cases} 已进入审批流转，开始自动审批...")
    approve_response = await client.post(
        f"{TASK_API_PREFIX}/{task_id}/approve",
        json={"is_approved": True},
    )
    approve_response.raise_for_status()
    approved_task = approve_response.json()
    print(f"任务 {case_index}/{total_cases} 审批已提交，当前状态={approved_task['status']}")

    final_task = await wait_for_status(
        client=client,
        task_id=task_id,
        target_statuses={"COMPLETED", "FAILED"},
        timeout_seconds=FINAL_TIMEOUT_SECONDS,
        progress_message=f"任务 {case_index}/{total_cases} 执行阶段状态更新: {{status}}",
    )

    duration_seconds = time.perf_counter() - started_at
    review_report = final_task.get("review_report") or {}
    issues_found = review_report.get("issues_found")

    print(
        f"任务 {case_index}/{total_cases} 结束，最终状态={final_task['status']}，"
        f"耗时={duration_seconds:.2f}s，issues_found={issues_found}"
    )

    return BenchmarkResult(
        case_index=case_index,
        prompt=prompt,
        task_id=task_id,
        status=final_task["status"],
        duration_seconds=duration_seconds,
        issues_found=issues_found if isinstance(issues_found, int) else None,
    )


def print_summary(results: list[BenchmarkResult]) -> None:
    """汇总并打印所有测试任务的基准结果。"""

    total_tasks = len(results)
    success_results = [result for result in results if result.status == "COMPLETED"]
    success_count = len(success_results)
    completion_rate = (success_count / total_tasks) * 100 if total_tasks else 0.0

    successful_durations = [result.duration_seconds for result in success_results]
    median_duration = statistics.median(successful_durations) if successful_durations else None

    reviewed_results = [result for result in results if result.issues_found is not None]
    total_issues_found = sum(result.issues_found or 0 for result in reviewed_results)
    average_issues_found = (
        total_issues_found / len(reviewed_results) if reviewed_results else 0.0
    )

    print("\n========== Benchmark Summary ==========")
    print(f"全链路完成率: {completion_rate:.0f}% ({success_count}/{total_tasks})")
    if median_duration is None:
        print("中位完成时长: N/A (无成功任务)")
    else:
        print(f"中位完成时长: {median_duration:.2f} 秒")
    print(f"Reviewer 检出改进点平均数: {average_issues_found:.2f}")

    print("\n逐任务结果:")
    for result in results:
        issues_text = str(result.issues_found) if result.issues_found is not None else "N/A"
        print(
            f"- 任务 {result.case_index}: status={result.status}, "
            f"duration={result.duration_seconds:.2f}s, issues_found={issues_text}, task_id={result.task_id}"
        )


async def check_server_health(client: httpx.AsyncClient) -> None:
    """检查目标服务是否可访问。"""

    print(f"检查服务健康状态: {BASE_URL}/")
    response = await client.get("/")
    response.raise_for_status()
    payload = response.json()
    print(f"服务健康检查通过: {payload}")


async def main() -> None:
    """执行双轮基准测试并输出统计指标。"""

    prompts = TASK_PROMPTS * TOTAL_ROUNDS
    total_cases = len(prompts)
    results: list[BenchmarkResult] = []

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        await check_server_health(client)

        for case_index, prompt in enumerate(prompts, start=1):
            try:
                result = await run_single_case(
                    client=client,
                    case_index=case_index,
                    total_cases=total_cases,
                    prompt=prompt,
                )
            except Exception as exc:
                print(f"任务 {case_index}/{total_cases} 执行异常: {exc}")
                result = BenchmarkResult(
                    case_index=case_index,
                    prompt=prompt,
                    task_id="N/A",
                    status="FAILED",
                    duration_seconds=0.0,
                    issues_found=None,
                )

            results.append(result)

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
