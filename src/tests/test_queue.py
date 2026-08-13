"""Tests for mypai_daemon.queue EventQueue."""

import pytest
from mypai_tools.daemon.queue import EventQueue


@pytest.mark.asyncio
async def test_queue_enqueue_and_priority() -> None:
    queue = EventQueue()

    # Enqueue items with different priorities
    await queue.enqueue(prompt="Normal webui prompt", mode="prompt", source="webui")
    await queue.enqueue(prompt="High priority steer", mode="steer", source="webui")
    await queue.enqueue(prompt="Background cron job", mode="prompt", source="cron")

    assert queue.depth() == 3

    # High-priority steer (priority 0) should come out first
    item1 = await queue.get_next()
    assert item1["mode"] == "steer"
    assert item1["prompt"] == "High priority steer"

    # Interactive turn (priority 1) should come out second
    item2 = await queue.get_next()
    assert item2["source"] == "webui"
    assert item2["prompt"] == "Normal webui prompt"

    # Background task (priority 2) should come out third
    item3 = await queue.get_next()
    assert item3["source"] == "cron"
    assert item3["prompt"] == "Background cron job"

    assert queue.depth() == 0


@pytest.mark.asyncio
async def test_queue_history() -> None:
    queue = EventQueue()
    item = await queue.enqueue(
        prompt="Test history prompt", mode="prompt", source="webui"
    )
    task_id = item["task_id"]

    next_item = await queue.get_next()
    assert next_item["task_id"] == task_id

    queue.mark_completed(task_id, {"status": "success", "output": "Done"})
    assert len(queue.history) == 1
    assert queue.history[0]["task_id"] == task_id
    assert queue.history[0]["status"] == "success"
