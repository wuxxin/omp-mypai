"""Prioritized Turn Queue with Priority-Flush State Machine for OMP RPC turns."""

import asyncio
import logging
import uuid
from enum import IntEnum
from typing import Any

logger = logging.getLogger("mypai_daemon.queue")


class Priority(IntEnum):
    """Priority levels for Turn Queue items."""

    ABORT = 0
    STEER = 1
    SYSTEM_EVENT = 2
    FOLLOWUP = 3
    USER_PROMPT = 4


class TurnQueue:
    """Prioritized Turn Queue for OMP RPC sessions.

    Resolution State Machine:
    1. Rule 1 (Abort Priority & Flush): If any `abort` or `abort_and_prompt` is queued,
       purges/clears the entire pending queue and executes the abort action immediately.
    2. Rule 2 (Steer Priority): Dequeues the next FIFO `steer` turn.
    3. Rule 3 (Followup Priority): Dequeues the next FIFO `followup` turn.
    4. Rule 4 (Prompt / Idle): Dequeues the next FIFO `prompt` turn only when the OMP session is idle.
    """

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._new_item_event = asyncio.Event()
        self.active_task_id: str | None = None
        self.history: list[dict[str, Any]] = []

    def _broadcast_queue_update(self) -> None:
        """Broadcast queue depth update via WebSocket if event loop is active."""
        try:
            from mypai_tools.daemon.api.ws import ws_manager

            cur_loop = asyncio.get_running_loop()
            cur_loop.create_task(
                ws_manager.broadcast({"event": "queue_updated", "queue_depth": self.depth()})
            )
        except RuntimeError:
            pass

    async def enqueue(
        self,
        prompt: str,
        mode: str = "prompt",
        source: str = "webui",
        context: dict[str, Any] | None = None,
        sender: str | None = None,
        is_result_call: bool = False,
        origin_job_id: str = "",
        priority: int = Priority.USER_PROMPT,
    ) -> dict[str, Any]:
        """Enqueue a turn into the Turn Queue."""
        async with self._lock:
            task_id = f"evt_{uuid.uuid4().hex[:8]}"
            clean_mode = str(mode or "prompt").lower().strip()
            if clean_mode in ("follow_up",):
                clean_mode = "followup"

            item: dict[str, Any] = {
                "task_id": task_id,
                "prompt": prompt,
                "mode": clean_mode,
                "source": source,
                "sender": sender,
                "context": context or {},
                "is_result_call": is_result_call,
                "origin_job_id": origin_job_id,
                "priority": priority,
                "status": "queued",
            }

            self._items.append(item)
            logger.info(
                "Enqueued turn '%s' (mode: %s, source: %s, is_result: %s, depth: %d)",
                task_id,
                clean_mode,
                source,
                is_result_call,
                len(self._items),
            )
            self._new_item_event.set()
            self._broadcast_queue_update()
            return item

    def purge_all(self) -> int:
        """Purge and drop all pending items in the queue."""
        count = len(self._items)
        self._items.clear()
        self._new_item_event.clear()
        logger.info("Purged all %d pending items from Turn Queue.", count)
        self._broadcast_queue_update()
        return count

    async def get_next(self, is_session_busy: bool = False) -> dict[str, Any]:
        """Get the next dispatchable turn according to the 4-rule priority state machine.

        Blocks asynchronously until a dispatchable item is available.
        """
        while True:
            async with self._lock:
                # Rule 1: Check for abort / abort_and_prompt
                for i, item in enumerate(self._items):
                    if item["mode"] in ("abort", "abort_and_prompt"):
                        target_item = self._items.pop(i)
                        # Purge the rest of the queue
                        purged_count = len(self._items)
                        self._items.clear()
                        if purged_count > 0:
                            logger.info(
                                "Purged %d items due to abort command '%s'.",
                                purged_count,
                                target_item["task_id"],
                            )
                        self.active_task_id = target_item["task_id"]
                        if not self._items:
                            self._new_item_event.clear()
                        self._broadcast_queue_update()
                        return target_item

                # Rule 2: Check for steer items (FIFO)
                for i, item in enumerate(self._items):
                    if item["mode"] == "steer":
                        target_item = self._items.pop(i)
                        self.active_task_id = target_item["task_id"]
                        if not self._items:
                            self._new_item_event.clear()
                        self._broadcast_queue_update()
                        return target_item

                # Rule 3: Check for followup items (FIFO)
                for i, item in enumerate(self._items):
                    if item["mode"] == "followup":
                        target_item = self._items.pop(i)
                        self.active_task_id = target_item["task_id"]
                        if not self._items:
                            self._new_item_event.clear()
                        self._broadcast_queue_update()
                        return target_item

                # Rule 4: If session is idle, check for prompts (FIFO)
                if not is_session_busy:
                    for i, item in enumerate(self._items):
                        if item["mode"] in ("prompt", "create"):
                            target_item = self._items.pop(i)
                            self.active_task_id = target_item["task_id"]
                            if not self._items:
                                self._new_item_event.clear()
                            self._broadcast_queue_update()
                            return target_item

                if not self._items:
                    self._new_item_event.clear()

            # Wait for new items or state changes
            await self._new_item_event.wait()
            await asyncio.sleep(0.05)

    def mark_completed(self, task_id: str, result: dict[str, Any]) -> None:
        """Mark task execution as completed and record in history."""
        if self.active_task_id == task_id:
            self.active_task_id = None
        self._broadcast_queue_update()
        result["task_id"] = task_id
        self.history.append(result)
        if len(self.history) > 100:
            self.history = self.history[-100:]

    def depth(self) -> int:
        """Return current pending queue depth."""
        return len(self._items)

    def peek_items(self) -> list[dict[str, Any]]:
        """Return a copy of pending items."""
        return list(self._items)


# Alias for backward compatibility in imports
EventQueue = TurnQueue
