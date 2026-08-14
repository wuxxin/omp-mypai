"""Tests for Event-Driven Asynchronous Queue Worker Architecture."""

import asyncio

import pytest
from conftest import FakeRpcClient
from mypai_tools.daemon.main import queue_worker_loop
from mypai_tools.daemon.queue import EventQueue
from mypai_tools.daemon.session_manager import OMPSessionManager
from mypai_tools.executors.omp_rpc_executor import dispatch_result_to_omp


@pytest.mark.asyncio
async def test_queue_worker_serialized_turns(tmp_path) -> None:
    """Verify that multiple prompt turns are serialized and executed by worker loop."""
    fake_client = FakeRpcClient()
    mgr = OMPSessionManager(agent_dir=str(tmp_path))
    mgr.rpc_client = fake_client

    queue = EventQueue()

    # Start worker loop as background task
    worker_task = asyncio.create_task(queue_worker_loop(queue, mgr))

    # Enqueue multiple turns
    await queue.enqueue(prompt="Turn 1 from webui", mode="prompt", source="webui")
    await queue.enqueue(prompt="Turn 2 from cron", mode="prompt", source="cron")
    await queue.enqueue(prompt="Turn 3 from signal", mode="prompt", source="signal")

    # Give worker loop time to process all items
    await asyncio.sleep(0.3)

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    # Verify history in queue
    assert len(queue.history) == 3
    prompts_in_history = [item["prompt"] for item in queue.history]
    assert prompts_in_history == [
        "Turn 1 from webui",
        "Turn 3 from signal",  # Signal has priority 1, cron has priority 2
        "[SYSTEM TRIGGER: CRON]\nTurn 2 from cron",
    ]


@pytest.mark.asyncio
async def test_queue_worker_midturn_interrupt(tmp_path) -> None:
    """Verify that a P0 steer interrupt executes mid-turn without waiting on lock."""
    fake_client = FakeRpcClient()
    mgr = OMPSessionManager(agent_dir=str(tmp_path))
    mgr.rpc_client = fake_client

    queue = EventQueue()

    # Enqueue standard prompt turn
    await queue.enqueue(prompt="Slow prompt turn", mode="prompt", source="webui")

    # Enqueue mid-turn steer interrupt (priority 0)
    await queue.enqueue(prompt="Immediate Steer Guidance", mode="steer", source="webui")

    worker_task = asyncio.create_task(queue_worker_loop(queue, mgr))
    await asyncio.sleep(0.3)

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    assert len(queue.history) == 2
    # Verify both commands were received by fake_client
    prompts_received = [p[0] for p in fake_client.prompts_received]
    assert "Immediate Steer Guidance" in prompts_received
    assert "Slow prompt turn" in prompts_received


@pytest.mark.asyncio
async def test_executor_result_dispatch_via_queue(tmp_path) -> None:
    """Verify that dispatch_result_to_omp enqueues into EventQueue without spawning RpcClient."""
    fake_client = FakeRpcClient()
    mgr = OMPSessionManager(agent_dir=str(tmp_path))
    mgr.rpc_client = fake_client

    queue = EventQueue()

    # Dispatch result action to OMP via EventQueue
    dispatch_result_to_omp(
        result_action="prompt",
        final_output="Executor Result Prompt Output",
        daemon_queue=queue,
        session_mgr=mgr,
    )

    await asyncio.sleep(0.1)

    assert queue.depth() == 1
    item = await queue.get_next()
    assert item["prompt"] == "Executor Result Prompt Output"
    assert item["source"] == "executor_result"
