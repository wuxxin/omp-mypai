"""Tests for mypai_daemon.queue TurnQueue."""

import pytest

from mypai_tools.daemon.queue import TurnQueue


@pytest.mark.asyncio
async def test_queue_enqueue_and_priority() -> None:
    queue = TurnQueue()

    # Enqueue items with different modes
    await queue.enqueue(prompt="Normal webui prompt", mode="prompt", source="webui")
    await queue.enqueue(prompt="Followup turn", mode="followup", source="webui")
    await queue.enqueue(prompt="High priority steer", mode="steer", source="webui")

    assert queue.depth() == 3

    # Steer item should come out first
    item1 = await queue.get_next(is_session_busy=True)
    assert item1["mode"] == "steer"
    assert item1["prompt"] == "High priority steer"

    # Followup item should come out next
    item2 = await queue.get_next(is_session_busy=True)
    assert item2["mode"] == "followup"
    assert item2["prompt"] == "Followup turn"

    # Prompt item should come out when session is idle
    item3 = await queue.get_next(is_session_busy=False)
    assert item3["mode"] == "prompt"
    assert item3["prompt"] == "Normal webui prompt"

    assert queue.depth() == 0


@pytest.mark.asyncio
async def test_queue_abort_and_purge() -> None:
    queue = TurnQueue()

    await queue.enqueue(prompt="Pending prompt 1", mode="prompt")
    await queue.enqueue(prompt="Pending prompt 2", mode="prompt")
    await queue.enqueue(prompt="Abort active turn", mode="abort")

    # Abort item purges all pending items and returns itself
    item = await queue.get_next(is_session_busy=True)
    assert item["mode"] == "abort"
    assert item["prompt"] == "Abort active turn"
    assert queue.depth() == 0


@pytest.mark.asyncio
async def test_queue_history() -> None:
    queue = TurnQueue()
    item = await queue.enqueue(prompt="Test history prompt", mode="prompt", source="webui")
    task_id = item["task_id"]

    next_item = await queue.get_next(is_session_busy=False)
    assert next_item["task_id"] == task_id

    queue.mark_completed(task_id, {"status": "success", "output": "Done"})
    assert len(queue.history) == 1
    assert queue.history[0]["task_id"] == task_id
    assert queue.history[0]["status"] == "success"
