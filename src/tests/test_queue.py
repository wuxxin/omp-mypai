"""Tests for mypai_daemon.queue EventQueue."""

import pytest
from mypai_tools.daemon.queue import EventQueue


@pytest.mark.asyncio
async def test_queue_enqueue_and_priority() -> None:
    queue = EventQueue()

    # Enqueue items with different priorities
    await queue.enqueue(prompt="Normal webui prompt", mode="prompt", source="webui")
    await queue.enqueue(prompt="Background cron job", mode="prompt", source="cron")
    await queue.enqueue(prompt="High priority steer", mode="steer", source="webui")
    await queue.enqueue(prompt="Abort active turn", mode="abort", source="webui")
    await queue.enqueue(prompt="UI response", mode="ui_interaction", source="webui")

    assert queue.depth() == 5

    # Priority 0 items (steer, abort, ui_interaction) should come out first
    p0_modes = set()
    for _ in range(3):
        item = await queue.get_next()
        p0_modes.add(item["mode"])
        assert item["priority"] == 0

    assert p0_modes == {"steer", "abort", "ui_interaction"}

    # Interactive turn (priority 1) should come out next
    item4 = await queue.get_next()
    assert item4["source"] == "webui"
    assert item4["prompt"] == "Normal webui prompt"

    # Background task (priority 2) should come out last
    item5 = await queue.get_next()
    assert item5["source"] == "cron"
    assert item5["prompt"] == "Background cron job"

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
