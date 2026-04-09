"""轻量级任务事件发布订阅管理器。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator


class TaskStreamManager:
    """按 task_id 管理 SSE 订阅队列。"""

    def __init__(self) -> None:
        self.queues: dict[str, list[asyncio.Queue[str]]] = {}
        self._lock = asyncio.Lock()
        self._terminal_statuses = {"COMPLETED", "FAILED"}

    async def publish(self, task_id: str, event_type: str, data: str) -> None:
        """向指定任务的全部订阅者发布 SSE 消息。"""

        normalized_data = data.replace("\r\n", "\n").replace("\r", "\n")
        data_lines = normalized_data.split("\n")
        message = f"event: {event_type}\n" + "".join(f"data: {line}\n" for line in data_lines) + "\n"
        async with self._lock:
            subscribers = list(self.queues.get(task_id, []))

        for queue in subscribers:
            await queue.put(message)

    async def subscribe(self, task_id: str) -> AsyncGenerator[str, None]:
        """订阅指定任务的 SSE 事件流。"""

        queue: asyncio.Queue[str] = asyncio.Queue()
        async with self._lock:
            self.queues.setdefault(task_id, []).append(queue)

        try:
            while True:
                message = await queue.get()
                yield message

                if self._is_terminal_event(message):
                    break
        finally:
            async with self._lock:
                subscribers = self.queues.get(task_id, [])
                if queue in subscribers:
                    subscribers.remove(queue)
                if not subscribers and task_id in self.queues:
                    del self.queues[task_id]

    def _is_terminal_event(self, message: str) -> bool:
        """判断消息是否为终态事件。"""

        if not message.startswith("event: status_update"):
            return False
        return any(f"data: {status}\n" in message for status in self._terminal_statuses)


stream_manager = TaskStreamManager()
