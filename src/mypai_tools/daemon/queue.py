"""Multi-Producer Single-Consumer (MPSC) Prioritized Event Queue for mypai_daemon."""

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger("mypai_daemon.queue")


class EventQueue:
    """Prioritized asyncio Queue serializing prompt turns from multiple producers.
    
    Priority ordering (lowest number = highest priority):
      Priority 0: 'steer', 'abort_and_prompt' (High-priority interrupts)
      Priority 1: 'webui', 'signal' (Interactive human turns)
      Priority 2: 'cron', 'spooler' (Background automated triggers)
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]] = (
            asyncio.PriorityQueue()
        )
        self._counter = 0
        self._lock = asyncio.Lock()
        self.active_task_id: str | None = None
        self.history: list[dict[str, Any]] = []

    def _get_priority(self, mode: str, source: str) -> int:
        clean_mode = str(mode or "").lower()
        clean_source = str(source or "").lower()

        if clean_mode in ("steer", "abort_and_prompt"):
            return 0
        if clean_source in ("webui", "signal"):
            return 1
        return 2

    async def enqueue(
        self,
        prompt: str,
        mode: str = "prompt",
        source: str = "webui",
        context: dict[str, Any] | None = None,
        sender: str | None = None,
    ) -> dict[str, Any]:
        """Enqueue a prompt turn for serialized execution."""
        async with self._lock:
            self._counter += 1
            task_id = f"evt_{uuid.uuid4().hex[:8]}"
            priority = self._get_priority(mode, source)

            item = {
                "task_id": task_id,
                "prompt": prompt,
                "mode": mode,
                "source": source,
                "sender": sender,
                "context": context or {},
                "priority": priority,
                "status": "queued",
            }

            await self._queue.put((priority, self._counter, item))
            logger.info(
                "Enqueued event '%s' (mode: %s, source: %s, priority: %d, depth: %d)",
                task_id,
                mode,
                source,
                priority,
                self._queue.qsize(),
            )
            return item

    async def get_next(self) -> dict[str, Any]:
        """Get the next prioritized turn item from queue."""
        _prio, _cnt, item = await self._queue.get()
        self.active_task_id = item["task_id"]
        return item

    def mark_completed(self, task_id: str, result: dict[str, Any]) -> None:
        """Mark task execution as completed and record in history."""
        if self.active_task_id == task_id:
            self.active_task_id = None
        result["task_id"] = task_id
        self.history.append(result)
        if len(self.history) > 100:
            self.history = self.history[-100:]
        self._queue.task_done()

    def depth(self) -> int:
        """Return current pending queue depth."""
        return self._queue.qsize()
