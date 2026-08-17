"""Test battery for mypai_daemon CronScheduler, executors, prompt resolution, and outcome handling."""

import pytest

from mypai_tools.daemon.queue import EventQueue
from mypai_tools.daemon.scheduler import CronScheduler
from mypai_tools.executors.http_executor import execute_http_job
from mypai_tools.executors.python_executor import execute_python_job
from mypai_tools.executors.shell_executor import execute_shell_job
from mypai_tools.tools import extract_omp_prompt

# ---------------------------------------------------------------------------
# 1. Prompt Extraction & Whitespace Stripping Unit Tests
# ---------------------------------------------------------------------------


def test_extract_omp_prompt_default_job() -> None:
    """Test default job structure (action='prompt', kwargs={'prompt': 'Audit...'}) doesn't send 'prompt'."""
    job = {
        "kind": "omp",
        "action": "prompt",
        "kwargs": {
            "prompt": "Audit active project tasks, verify pending commitments, and reflect on progress. Use 300 words."
        },
    }
    prompt = extract_omp_prompt(job)
    assert prompt == (
        "Audit active project tasks, verify pending commitments, and reflect on progress. Use 300 words."
    )


def test_extract_omp_prompt_whitespace_stripping() -> None:
    """Test leading and trailing whitespace is stripped from prompt strings."""
    job = {
        "kind": "omp",
        "action": "prompt",
        "kwargs": {"prompt": "  \n  Check status   \t"},
    }
    assert extract_omp_prompt(job) == "Check status"


def test_extract_omp_prompt_whitespace_only_is_empty() -> None:
    """Test a whitespace-only prompt string is evaluated as empty ("")."""
    job = {
        "kind": "omp",
        "action": "prompt",
        "kwargs": {"prompt": "   \n\t "},
    }
    assert extract_omp_prompt(job) == ""


def test_extract_omp_prompt_args_list() -> None:
    """Test prompt extraction from positional args list."""
    job = {
        "kind": "omp",
        "action": "prompt",
        "args": ["Execute background task"],
    }
    assert extract_omp_prompt(job) == "Execute background task"


def test_extract_omp_prompt_toplevel_prompt() -> None:
    """Test prompt extraction from top-level prompt key."""
    job = {
        "kind": "omp",
        "action": "prompt",
        "prompt": "Top-level prompt string",
    }
    assert extract_omp_prompt(job) == "Top-level prompt string"


def test_extract_omp_prompt_non_verb_action() -> None:
    """Test custom non-verb action string is used as prompt text."""
    job = {
        "kind": "omp",
        "action": "Custom prompt text in action",
    }
    assert extract_omp_prompt(job) == "Custom prompt text in action"


# ---------------------------------------------------------------------------
# 2. CronScheduler & Queue Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_scheduler_omp_job_with_queue(tmp_path) -> None:
    """Test CronScheduler enqueues correct prompt into EventQueue instead of 'prompt'."""
    queue = EventQueue()
    scheduler = CronScheduler(agent_dir=str(tmp_path), daemon_queue=queue)
    job = {
        "id": "cron_default_1",
        "name": "Audit Task",
        "cron": "now",
        "kind": "omp",
        "action": "prompt",
        "kwargs": {
            "prompt": "Audit active project tasks, verify pending commitments, and reflect on progress. Use 300 words."
        },
    }

    res = await scheduler.run_job(job)
    assert res["status"] == "queued"
    assert queue.depth() == 1

    item = await queue.get_next()
    assert item["prompt"] == (
        "Audit active project tasks, verify pending commitments, and reflect on progress. Use 300 words."
    )
    assert item["prompt"] != "prompt"


@pytest.mark.asyncio
async def test_cron_scheduler_omp_job_empty_prompt_returns_error(tmp_path) -> None:
    """Test CronScheduler returns error when OMP job has empty prompt."""
    queue = EventQueue()
    scheduler = CronScheduler(agent_dir=str(tmp_path), daemon_queue=queue)
    job = {
        "id": "cron_empty_1",
        "name": "Empty Prompt Task",
        "cron": "now",
        "kind": "omp",
        "action": "prompt",
        "kwargs": {"prompt": "   \n\t  "},
    }

    res = await scheduler.run_job(job)
    assert res["status"] == "error"
    assert "Empty prompt" in res.get("error", "")
    assert queue.depth() == 0


@pytest.mark.asyncio
async def test_cron_scheduler_global_toggle(tmp_path) -> None:
    """Test global cron execution toggle enables and disables task execution."""
    scheduler = CronScheduler(agent_dir=str(tmp_path))
    assert scheduler.is_cron_execution_enabled() is True

    scheduler.disable_cron_execution()
    assert scheduler.is_cron_execution_enabled() is False

    job = {
        "id": "test_disabled_1",
        "name": "Skipped Job",
        "cron": "now",
        "kind": "shell",
        "action": "echo",
        "args": ["Hello"],
    }
    res = await scheduler.run_job(job)
    assert res["status"] == "skipped"
    assert res["reason"] == "cron_disabled"

    scheduler.enable_cron_execution()
    assert scheduler.is_cron_execution_enabled() is True


# ---------------------------------------------------------------------------
# 3. Executors Outcome & Error Prompt Battery Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shell_executor_outcomes() -> None:
    """Test shell job executor success and failure outcomes with result_error_prompt."""
    # Success outcome
    job_success = {
        "name": "Echo Success",
        "kind": "shell",
        "action": "echo",
        "args": ["Task Done"],
        "result_prompt": "SUCCESS: #[_OUTPUT]",
    }
    res_s = await execute_shell_job(job_success)
    assert res_s["status"] == "success"
    assert "SUCCESS: Task Done" in res_s["output"]

    # Failure outcome with result_error_prompt
    job_fail = {
        "name": "Command Fail",
        "kind": "shell",
        "action": "ls /nonexistent_directory_xyz",
        "result_error_prompt": "FAIL: Code #[_RETURN_CODE]",
    }
    res_f = await execute_shell_job(job_fail)
    assert res_f["status"] == "error"
    assert "FAIL: Code" in res_f["output"]

    # Failure outcome with whitespace-only result_error_prompt (falls back to raw error)
    job_fail_ws = {
        "name": "Command Fail Whitespace Error Prompt",
        "kind": "shell",
        "action": "ls /nonexistent_directory_xyz",
        "result_error_prompt": "   \n\t  ",
    }
    res_f_ws = await execute_shell_job(job_fail_ws)
    assert res_f_ws["status"] == "error"
    assert "nonexistent_directory_xyz" in res_f_ws["error"]


@pytest.mark.asyncio
async def test_python_executor_outcomes() -> None:
    """Test python job executor success and failure outcomes with result_error_prompt."""
    # Success outcome
    job_success = {
        "name": "Python Lambda Success",
        "kind": "python",
        "action": "lambda args, kwargs: args[0] * 2",
        "args": [21],
        "result_prompt": "CALCULATED: #[_OUTPUT]",
    }
    res_s = await execute_python_job(job_success)
    assert res_s["status"] == "success"
    assert "CALCULATED: 42" in res_s["output"]

    # Failure outcome with result_error_prompt
    job_fail = {
        "name": "Python Syntax Error",
        "kind": "python",
        "action": "lambda: 1 / 0",
        "result_error_prompt": "PYTHON_ERROR: #[_ERROR]",
    }
    res_f = await execute_python_job(job_fail)
    assert res_f["status"] == "error"
    assert "PYTHON_ERROR: division by zero" in res_f["output"]


@pytest.mark.asyncio
async def test_http_executor_outcomes() -> None:
    """Test HTTP job executor success and failure outcomes with result_error_prompt."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_resp_success = MagicMock()
    mock_resp_success.status_code = 200
    mock_resp_success.json.return_value = {"status": "ok"}
    mock_resp_success.text = '{"status": "ok"}'

    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 400
    mock_resp_fail.json.side_effect = ValueError("Not JSON")
    mock_resp_fail.text = "Bad Request"

    mock_client = AsyncMock()
    mock_client.request.side_effect = [mock_resp_success, mock_resp_fail]
    mock_client.__aenter__.return_value = mock_client

    with (
        patch("mypai_tools.executors.http_executor.dispatch_result_to_omp") as mock_dispatch,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        job_success = {
            "name": "HTTP Success",
            "kind": "http",
            "action": "GET",
            "args": ["http://api.local/test"],
            "result_prompt": "HTTP_OK: #[_OUTPUT]",
            "result_action": "prompt",
        }
        res_s = await execute_http_job(job_success)
        assert res_s["status"] == "success"
        assert res_s["output"] == '{"status": "ok"}'
        mock_dispatch.assert_called_with(
            "prompt",
            'HTTP_OK: {"status": "ok"}',
            daemon_queue=None,
            session_mgr=None,
            job_id="",
        )

        job_fail = {
            "name": "HTTP Failure",
            "kind": "http",
            "action": "GET",
            "args": ["http://api.local/fail"],
            "result_error_prompt": "HTTP_FAIL_CODE: #[_HTTP_CODE]",
            "result_action": "steer",
        }
        res_f = await execute_http_job(job_fail)
        assert res_f["status"] == "error"
        mock_dispatch.assert_called_with(
            "steer",
            "HTTP_FAIL_CODE: 400",
            daemon_queue=None,
            session_mgr=None,
            job_id="",
        )
