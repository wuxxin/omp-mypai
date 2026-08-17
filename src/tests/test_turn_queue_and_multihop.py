"""Unit and integration tests for TurnQueue priority-flush state machine, running_jobs concurrency, and multi-hop task.result execution."""

import asyncio
from pathlib import Path

import pytest

from mypai_tools.daemon.queue import TurnQueue
from mypai_tools.daemon.scheduler import CronScheduler
from mypai_tools.executors.shell_executor import execute_shell_job
from mypai_tools.host_tools.cron_tools import cron_add_job_fn


@pytest.mark.asyncio
async def test_turn_queue_priority_state_machine() -> None:
    """Test 4-rule priority state machine:
    Rule 1 (Abort Priority): abort purges entire queue.
    Rule 2 (Steer Priority): steer before followup and prompt.
    Rule 3 (Followup Priority): followup before prompt.
    Rule 4 (Prompt / Idle): prompt dequeued when session is idle.
    """
    queue = TurnQueue()

    # Enqueue mixed items
    await queue.enqueue(prompt="Normal prompt 1", mode="prompt")
    await queue.enqueue(prompt="Followup turn", mode="followup")
    await queue.enqueue(prompt="Steer turn", mode="steer")
    await queue.enqueue(prompt="Normal prompt 2", mode="prompt")

    # While busy: only Steer and Followup can be dequeued
    item1 = await queue.get_next(is_session_busy=True)
    assert item1["mode"] == "steer"
    assert item1["prompt"] == "Steer turn"

    item2 = await queue.get_next(is_session_busy=True)
    assert item2["mode"] == "followup"
    assert item2["prompt"] == "Followup turn"

    # Now with session idle: FIFO prompt 1
    item3 = await queue.get_next(is_session_busy=False)
    assert item3["mode"] == "prompt"
    assert item3["prompt"] == "Normal prompt 1"

    # Enqueue more prompts and an abort_and_prompt
    await queue.enqueue(prompt="Pending prompt 3", mode="prompt")
    await queue.enqueue(prompt="Pending prompt 4", mode="prompt")
    await queue.enqueue(prompt="Emergency abort prompt", mode="abort_and_prompt")

    # Dequeue next: abort_and_prompt must purge all pending items and return itself
    item_abort = await queue.get_next(is_session_busy=True)
    assert item_abort["mode"] == "abort_and_prompt"
    assert item_abort["prompt"] == "Emergency abort prompt"

    # Queue must now be empty
    assert queue.depth() == 0


@pytest.mark.asyncio
async def test_running_jobs_duplicate_prevention(tmp_path: Path) -> None:
    """Test overlapping cron job prevention policy (skip & log notice when job_id in running_jobs)."""
    agent_dir = str(tmp_path)
    queue = TurnQueue()
    scheduler = CronScheduler(agent_dir=agent_dir, daemon_queue=queue)

    job_dict = {
        "id": "slow_job_001",
        "name": "Slow Shell Job",
        "cron": "* * * * *",
        "kind": "shell",
        "action": "sleep 0.5",
        "opts": {"timeout_sec": 5},
    }

    # Start first invocation as background task
    task1 = asyncio.create_task(scheduler.run_job(job_dict))
    await asyncio.sleep(0.05)

    # Verify job is tracked in running_jobs
    assert "slow_job_001" in scheduler.running_jobs

    # Attempt second simultaneous invocation of same job_id -> must be skipped
    res2 = await scheduler.run_job(job_dict)
    assert res2["status"] == "skipped"
    assert res2["reason"] == "already_running"

    # Wait for first invocation to complete
    res1 = await task1
    assert res1["status"] == "success"

    # Verify job is removed from running_jobs upon completion
    assert "slow_job_001" not in scheduler.running_jobs


@pytest.mark.asyncio
async def test_multi_hop_task_result_execution_flow(tmp_path: Path) -> None:
    """Test multi-hop task.result execution flow:
    Background executor completes -> evaluates result prompt -> enqueues TurnQueue turn with is_result_call=True.
    """
    queue = TurnQueue()

    job_dict = {
        "id": "backup_db_job",
        "name": "Database Backup",
        "cron": "0 2 * * *",
        "kind": "shell",
        "action": "echo 'Backup OK: 42 tables dumped'",
        "result": {
            "action": "prompt",
            "prompt": "DB Backup completed: #{_OUTPUT}. Exit: #{_RETURN_CODE}",
        },
    }

    # Execute shell job with TurnQueue attached
    res = await execute_shell_job(job_dict, daemon_queue=queue)
    await asyncio.sleep(0.05)
    assert res["status"] == "success"
    assert res["return_code"] == 0

    # Verify TurnQueue received the result turn with lineage tagging
    assert queue.depth() == 1
    item = await queue.get_next(is_session_busy=False)
    assert item["is_result_call"] is True
    assert item["origin_job_id"] == "backup_db_job"
    assert item["source"] == "executor_result"
    assert "DB Backup completed: Backup OK: 42 tables dumped" in item["prompt"]
    assert "Exit: 0" in item["prompt"]


@pytest.mark.asyncio
async def test_host_tools_and_web_api_synergy(test_client, tmp_path: Path) -> None:
    """Test creating a job via Host Tools and querying/running via Web API."""
    agent_dir = str(tmp_path)

    # 1. Add job via Host Tool
    res_tool = await cron_add_job_fn(
        name="Synergy Health Check",
        cron="*/5 * * * *",
        kind="shell",
        action="echo 'healthy'",
        description="System health monitor",
        opts={"timeout_sec": 10},
        agent_dir=agent_dir,
    )
    assert res_tool["status"] == "scheduled"
    job_id = res_tool["job"]["id"]

    # 2. Query via Web API
    res_api = test_client.get("/api/v1/cron/jobs")
    assert res_api.status_code == 200
    jobs = res_api.json()
    assert any(j["id"] == job_id for j in jobs)

    # 3. Trigger run_once via Web API
    res_run = test_client.post(
        "/api/v1/cron/jobs/run_once",
        json={"name": "Synergy Health Check", "kind": "shell", "action": "echo 'healthy'"},
    )
    assert res_run.status_code == 200
    assert res_run.json()["status"] == "scheduled"
