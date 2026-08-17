"""Refactoring and Spec Coverage Unit & Integration Test Suite.

Verifies evaluate_and_dispatch_result_prompt edge cases, format_system_trigger_prompt sources,
CronScheduler WebSocket broadcasting, one-shot auto-disabling, and full-cycle scheduler execution of all example jobs.
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypai_tools.daemon.queue import TurnQueue
from mypai_tools.daemon.scheduler import CronScheduler
from mypai_tools.persistence import CronJobModel, get_db_session
from mypai_tools.tools import (
    build_internal_vars,
    evaluate_and_dispatch_result_prompt,
    format_system_trigger_prompt,
    load_jobs_file,
)


def test_evaluate_and_dispatch_result_prompt_flat_and_nested() -> None:
    """Verify evaluate_and_dispatch_result_prompt with flat and nested result dictionaries."""
    mock_dispatch = MagicMock()

    # 1. Flat dictionary attributes success
    job_flat = {
        "name": "Flat Job",
        "result_action": "prompt",
        "result_prompt": "Flat Success: #[_OUTPUT]",
    }
    vars_flat = build_internal_vars(job_flat, return_code=0, output="OK")
    out_flat = evaluate_and_dispatch_result_prompt(
        job_flat,
        vars_flat,
        is_success=True,
        default_output="OK",
        dispatch_fn=mock_dispatch,
    )
    assert out_flat == "Flat Success: OK"
    mock_dispatch.assert_called_with(
        "prompt", "Flat Success: OK", daemon_queue=None, session_mgr=None, job_id=""
    )

    # 2. Nested dictionary error prompt
    mock_dispatch.reset_mock()
    job_nested = {
        "name": "Nested Job",
        "result": {
            "action": "steer",
            "prompt": "Success: #[_OUTPUT]",
            "error_prompt": "Error in #[_JOB_NAME]: #[_ERROR]",
        },
    }
    vars_nested = build_internal_vars(job_nested, return_code=1, error="Crash")
    out_nested = evaluate_and_dispatch_result_prompt(
        job_nested,
        vars_nested,
        is_success=False,
        default_output="Crash",
        dispatch_fn=mock_dispatch,
    )
    assert out_nested == "Error in Nested Job: Crash"
    mock_dispatch.assert_called_with(
        "steer", "Error in Nested Job: Crash", daemon_queue=None, session_mgr=None, job_id=""
    )

    # 3. Empty result.prompt on success returns default_output
    mock_dispatch.reset_mock()
    job_empty = {"name": "Silent Job", "result": {"action": "prompt", "prompt": ""}}
    vars_empty = build_internal_vars(job_empty, return_code=0, output="Silent Output")
    out_empty = evaluate_and_dispatch_result_prompt(
        job_empty,
        vars_empty,
        is_success=True,
        default_output="Silent Output",
        dispatch_fn=mock_dispatch,
    )
    assert out_empty == "Silent Output"

    # 4. Fallback to default_output with header when no # macro in template string
    mock_dispatch.reset_mock()
    job_no_macro = {"result_action": "prompt", "result_prompt": "Header Only"}
    vars_no_macro = build_internal_vars(job_no_macro, return_code=0, output="Body Text")
    out_no_macro = evaluate_and_dispatch_result_prompt(
        job_no_macro,
        vars_no_macro,
        is_success=True,
        default_output="Body Text",
        dispatch_fn=mock_dispatch,
    )
    assert out_no_macro == "Header Only\nBody Text"


def test_format_system_trigger_prompt_all_sources() -> None:
    """Verify format_system_trigger_prompt for human, cron, spooler, and executor_result sources."""
    context = {"name": "Daily Backup"}

    # Human sources pass through unchanged
    for src in ("webui", "signal", "interactive", "human", ""):
        assert format_system_trigger_prompt("Run task", source=src, context=context) == "Run task"

    # Pre-existing [SYSTEM TRIGGER header passes through unchanged
    pre_formatted = "[SYSTEM TRIGGER: CUSTOM]\nCustom task"
    assert (
        format_system_trigger_prompt(pre_formatted, source="cron", context=context) == pre_formatted
    )

    # Cron source
    cron_fmt = format_system_trigger_prompt("Check stats", source="cron", context=context)
    assert cron_fmt == "[SYSTEM TRIGGER: CRON (Daily Backup)]\nCheck stats"

    # Executor result source
    exec_fmt = format_system_trigger_prompt(
        "Task finished", source="executor_result", context=context
    )
    assert exec_fmt == "[SYSTEM TRIGGER: EXECUTOR_RESULT (Daily Backup)]\nTask finished"

    # Spooler source
    spool_fmt = format_system_trigger_prompt("Speech STT", source="spooler")
    assert spool_fmt == "[SYSTEM TRIGGER: INPUT_SPOOLER]\nSpeech STT"


@pytest.mark.asyncio
async def test_scheduler_run_job_websocket_broadcast_and_oneshot(tmp_path) -> None:
    """Verify CronScheduler.run_job broadcasts WebSocket event and auto-disables one-shot jobs."""
    agent_dir = str(tmp_path)
    queue = TurnQueue()
    scheduler = CronScheduler(agent_dir=agent_dir, daemon_queue=queue)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Populate SQLite database with a one-shot job
    session = get_db_session(agent_dir)
    db_job = CronJobModel(
        id="oneshot_1",
        name="One-Shot Task",
        cron="now",
        kind="python",
        action="lambda args, kwargs: 'oneshot_done'",
        enabled=True,
        created_at=now_iso,
        updated_at=now_iso,
    )
    session.add(db_job)
    session.commit()
    session.close()

    mock_broadcast = AsyncMock()
    with patch("mypai_tools.daemon.api.ws.ws_manager.broadcast", new=mock_broadcast):
        job_dict = {
            "id": "oneshot_1",
            "name": "One-Shot Task",
            "cron": "now",
            "kind": "python",
            "action": "lambda args, kwargs: 'oneshot_done'",
        }
        res = await scheduler.run_job(job_dict)

        assert res["status"] == "success"
        assert res["return_code"] == 0
        assert mock_broadcast.called

        broadcast_payload = mock_broadcast.call_args[0][0]
        assert broadcast_payload["event"] == "cron_task_completed"
        assert broadcast_payload["job_id"] == "oneshot_1"
        assert broadcast_payload["name"] == "One-Shot Task"
        assert broadcast_payload["kind"] == "python"
        assert broadcast_payload["status"] == "success"

    # Verify one-shot job was disabled in DB
    session = get_db_session(agent_dir)
    updated_job = session.query(CronJobModel).filter_by(id="oneshot_1").first()
    assert updated_job is not None
    assert updated_job.enabled is False
    assert updated_job.total_runs == 1
    assert updated_job.last_returncode == 0
    session.close()


@pytest.mark.asyncio
async def test_example_jobs_scheduler_full_cycle(tmp_path) -> None:
    """Import example_jobs.yaml into CronScheduler and run full execution cycle for all 4 jobs."""
    agent_dir = str(tmp_path)
    queue = TurnQueue()
    scheduler = CronScheduler(agent_dir=agent_dir, daemon_queue=queue)
    now_iso = datetime.now(timezone.utc).isoformat()

    yaml_path = os.path.join(os.path.dirname(__file__), "../../config/example_jobs.yaml")
    example_jobs = load_jobs_file(yaml_path)
    assert len(example_jobs) == 4

    session = get_db_session(agent_dir)
    for idx, j in enumerate(example_jobs):
        db_j = CronJobModel(
            id=f"ex_{idx + 1}",
            name=j["name"],
            cron=j.get("cron", "* * * * *"),
            kind=j.get("kind", "omp"),
            action=j.get("action", ""),
            enabled=True,
            created_at=now_iso,
            updated_at=now_iso,
        )
        session.add(db_j)
    session.commit()
    session.close()

    # Mock HTTP client for HTTP example job
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.text = '{"status": "ok"}'
    mock_http_resp.json.return_value = {"status": "ok"}

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_http_resp
    mock_client.__aenter__.return_value = mock_client

    # Mock Shell subprocess for shell example job
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"DB Audit OK", b"")

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        patch("asyncio.create_subprocess_shell", return_value=mock_proc),
        patch("mypai_tools.executors.omp_rpc_executor.execute_omp_rpc_job") as mock_omp_exec,
    ):
        mock_omp_exec.return_value = {
            "status": "success",
            "return_code": 0,
            "output": "OMP OK",
        }

        for idx, j in enumerate(example_jobs):
            job_dict = dict(j)
            job_dict["id"] = f"ex_{idx + 1}"
            res = await scheduler.run_job(job_dict)
            assert res["status"] in ("success", "queued"), (
                f"Job {j['name']} ({j.get('kind')}) failed: {res}"
            )

    # Verify telemetry for all 4 jobs in SQLite DB
    session = get_db_session(agent_dir)
    for idx in range(1, 5):
        db_j = session.query(CronJobModel).filter_by(id=f"ex_{idx}").first()
        assert db_j is not None
        assert db_j.total_runs == 1
        assert db_j.last_run_at != ""
        assert db_j.last_returncode == 0
    session.close()
