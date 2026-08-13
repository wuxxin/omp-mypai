"""Deep robustness unit tests covering concurrent producers, scheduler DB sync telemetry, executor error templates, and invalid API payloads."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mypai_tools.daemon.queue import EventQueue
from mypai_tools.daemon.scheduler import CronScheduler
from mypai_tools.executors.python_executor import execute_python_job
from mypai_tools.executors.shell_executor import execute_shell_job
from mypai_tools.persistence import CronJobModel, get_db_session


# 1. Multi-Producer Concurrent Queue Stress Test
@pytest.mark.asyncio
async def test_queue_concurrent_multi_producers() -> None:
    queue = EventQueue()

    async def producer(source: str, count: int, mode: str = "prompt") -> None:
        for i in range(count):
            await queue.enqueue(
                prompt=f"Prompt {i} from {source}",
                mode=mode,
                source=source,
            )

    # Launch 4 concurrent producers
    await asyncio.gather(
        producer("webui", 10, mode="prompt"),
        producer("signal", 10, mode="prompt"),
        producer("cron", 10, mode="prompt"),
        producer("steer_source", 5, mode="steer"),
    )

    assert queue.depth() == 35

    # Pop all items and verify steer priority items come out first
    steer_count = 0
    for _ in range(5):
        item = await queue.get_next()
        if item["mode"] == "steer":
            steer_count += 1
    assert steer_count == 5


# 2. Scheduler Database Telemetry & One-Shot Disabling
@pytest.mark.asyncio
async def test_scheduler_telemetry_and_oneshot(tmp_path: Path) -> None:
    proj_dir = str(tmp_path)
    session = get_db_session(proj_dir)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Insert a one-shot job
    now_job = CronJobModel(
        id="oneshot_1",
        name="One-Shot Telemetry Job",
        cron="now",
        kind="shell",
        action="echo telemetry_test",
        enabled=True,
        created_at=now_iso,
        updated_at=now_iso,
    )
    session.add(now_job)
    session.commit()
    session.close()

    scheduler = CronScheduler(agent_dir=proj_dir)
    scheduler.sync_jobs_from_db()
    assert len(scheduler.scheduled_job_ids) == 1

    # Run the job manually through scheduler
    res = await scheduler.run_job(
        {
            "id": "oneshot_1",
            "name": "One-Shot Telemetry Job",
            "cron": "now",
            "kind": "shell",
            "action": "echo telemetry_test",
        }
    )
    assert res["status"] == "success" or res["return_code"] == 0

    # Verify database telemetry recorded and enabled set to False
    session2 = get_db_session(proj_dir)
    updated_job = session2.query(CronJobModel).filter_by(id="oneshot_1").first()
    assert updated_job is not None
    assert updated_job.enabled is False
    assert updated_job.total_calls == 1
    assert updated_job.last_returncode == 0
    assert "telemetry_test" in (updated_job.last_output or "")
    session2.close()


# 3. Shell Executor Error Template Substitution
@pytest.mark.asyncio
async def test_shell_executor_error_template() -> None:
    job = {
        "name": "Failing Shell Command",
        "kind": "shell",
        "action": "sh -c 'echo custom_error_msg >&2; exit 1'",
        "result_error_prompt": "Command failed with code #[_RETURN_CODE]! Output: #[_ERROR]",
    }
    res = await execute_shell_job(job)
    assert res["return_code"] == 1
    assert "Command failed with code 1" in res["output"]
    assert "custom_error_msg" in res["output"]


# 4. Python Executor Syntax & Runtime Error Resilience
@pytest.mark.asyncio
async def test_python_executor_invalid_syntax() -> None:
    job = {
        "name": "Syntax Error Job",
        "kind": "python",
        "action": "def invalid_syntax(:",
        "result_error_prompt": "Syntax error caught: #[_STDERR]",
    }
    res = await execute_python_job(job)
    assert res["return_code"] == 1
    assert "error" in res or res["status"] == "error"


# 5. REST API Uninitialized State & Invalid Payload Robustness
def test_api_uninitialized_queue_error(test_client) -> None:
    # Temporarily uninitialize queue
    original_queue = test_client.app.state.daemon_queue
    test_client.app.state.daemon_queue = None

    try:
        res = test_client.post(
            "/api/v1/session/prompt",
            json={"prompt": "Test prompt"},
        )
        assert res.status_code == 500
        assert "EventQueue uninitialized" in res.json()["detail"]
    finally:
        test_client.app.state.daemon_queue = original_queue


def test_api_invalid_signal_webhook_json(test_client) -> None:
    res = test_client.post(
        "/api/v1/signal/webhook",
        content="Invalid Raw String Payload",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "error"
