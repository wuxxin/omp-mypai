"""Test Battery for example_jobs.yaml configuration file.

Executes each example job once for Success outcome and once for Failure outcome,
verifying result_prompt and result_error_prompt macro variable expansion.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from conftest import FakeRpcClient
from mypai_tools.executors.http_executor import execute_http_job
from mypai_tools.executors.omp_rpc_executor import execute_omp_rpc_job
from mypai_tools.executors.python_executor import execute_python_job
from mypai_tools.executors.shell_executor import execute_shell_job

EXAMPLE_JOBS_PATH = Path(__file__).resolve().parents[2] / "config" / "example_jobs.yaml"


def load_example_jobs() -> list[dict]:
    """Load example jobs list from config/example_jobs.yaml."""
    with open(EXAMPLE_JOBS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("jobs", [])


def test_example_jobs_yaml_parsing() -> None:
    """Verify that example_jobs.yaml exists and contains 4 valid job definitions."""
    assert EXAMPLE_JOBS_PATH.exists(), f"File not found: {EXAMPLE_JOBS_PATH}"
    jobs = load_example_jobs()
    assert len(jobs) == 4
    for job in jobs:
        assert "name" in job
        assert "cron" in job
        assert "kind" in job
        assert "action" in job


@pytest.mark.asyncio
async def test_example_job_1_omp_success_and_failure() -> None:
    """Test Job 1 (OMP RPC job): success and failure outcomes."""
    jobs = load_example_jobs()
    job = next(j for j in jobs if j["kind"] == "omp")
    fake_client = FakeRpcClient()

    # Success outcome
    res_success = await execute_omp_rpc_job(job, client=fake_client)
    assert res_success["status"] == "success"
    assert res_success["return_code"] == 0

    # Failure outcome: empty prompt triggers validation error
    failing_job = dict(job)
    failing_job["kwargs"] = {"prompt": ""}
    res_fail = await execute_omp_rpc_job(failing_job, client=fake_client)
    assert res_fail["status"] == "error"
    assert res_fail["return_code"] == 1
    assert "Empty prompt" in res_fail["error"]


@pytest.mark.asyncio
async def test_example_job_2_http_success_and_failure() -> None:
    """Test Job 2 (HTTP job): success and failure outcomes with macro expansion."""
    jobs = load_example_jobs()
    job = next(j for j in jobs if j["kind"] == "http")
    mock_queue = AsyncMock()

    # Success outcome (HTTP 200)
    mock_success_resp = MagicMock()
    mock_success_resp.status_code = 200
    mock_success_resp.text = '{"status": "reflected"}'
    mock_success_resp.json.return_value = {"status": "reflected"}

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_success_resp
        res_success = await execute_http_job(job, daemon_queue=mock_queue)
        await asyncio.sleep(0.01)

        assert res_success["status"] == "success"
        assert res_success["return_code"] == 0
        assert res_success["output"] == '{"status": "reflected"}'
        assert mock_queue.enqueue.called
        dispatched_prompt = mock_queue.enqueue.call_args[1]["prompt"]
        assert (
            "Hindsight Reflection Sweep for Hindsight Reflection Sweep completed with status 200"
            in dispatched_prompt
        )

    # Failure outcome (HTTP 500)
    mock_fail_resp = MagicMock()
    mock_fail_resp.status_code = 500
    mock_fail_resp.text = '{"error": "Database Connection Lost"}'
    mock_fail_resp.json.return_value = {"error": "Database Connection Lost"}
    mock_queue.reset_mock()

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_fail_resp
        res_fail = await execute_http_job(job, daemon_queue=mock_queue)
        await asyncio.sleep(0.01)

        assert res_fail["status"] == "error"
        assert res_fail["return_code"] == 500
        assert mock_queue.enqueue.called
        dispatched_err_prompt = mock_queue.enqueue.call_args[1]["prompt"]
        assert (
            "CRON ERROR: http job 'Hindsight Reflection Sweep' failed with http code 500"
            in dispatched_err_prompt
        )
        assert "#[_JOB_NAME]" not in dispatched_err_prompt  # Verifies macro expanded


@pytest.mark.asyncio
async def test_example_job_3_shell_success_and_failure() -> None:
    """Test Job 3 (Shell job): success and failure outcomes with macro expansion."""
    jobs = load_example_jobs()
    job = next(j for j in jobs if j["kind"] == "shell")
    mock_queue = AsyncMock()

    # Success outcome: override command to execute python echo
    job_success = dict(job)
    job_success["action"] = "python3"
    job_success["args"] = ["-c", "print('DB Audit OK')"]

    res_success = await execute_shell_job(job_success, daemon_queue=mock_queue)
    await asyncio.sleep(0.01)
    assert res_success["status"] == "success"
    assert res_success["return_code"] == 0
    assert "DB Audit OK" in res_success["output"]
    assert mock_queue.enqueue.called
    dispatched_prompt = mock_queue.enqueue.call_args[1]["prompt"]
    assert (
        "Nightly Database Audit completed successfully for Nightly Database Backup & Audit"
        in dispatched_prompt
    )

    # Failure outcome: override command to exit 1 with stderr
    job_fail = dict(job)
    job_fail["action"] = "python3"
    job_fail["args"] = [
        "-c",
        "import sys; sys.stderr.write('Table corruption detected'); sys.exit(1)",
    ]
    mock_queue.reset_mock()

    res_fail = await execute_shell_job(job_fail, daemon_queue=mock_queue)
    await asyncio.sleep(0.01)
    assert res_fail["status"] == "error"
    assert res_fail["return_code"] == 1
    assert "Table corruption detected" in res_fail["error"]
    assert mock_queue.enqueue.called
    dispatched_err_prompt = mock_queue.enqueue.call_args[1]["prompt"]
    assert (
        "CRON ERROR: Shell job 'Nightly Database Backup & Audit' failed with return code 1"
        in dispatched_err_prompt
    )


@pytest.mark.asyncio
async def test_example_job_4_python_success_and_failure() -> None:
    """Test Job 4 (Python job): success and failure outcomes with macro expansion."""
    jobs = load_example_jobs()
    job = next(j for j in jobs if j["kind"] == "python")
    mock_queue = AsyncMock()

    # Success outcome (runs original lambda)
    res_success = await execute_python_job(job, daemon_queue=mock_queue)
    await asyncio.sleep(0.01)
    assert res_success["status"] == "success"
    assert res_success["return_code"] == 0
    assert '{"status": "healthy", "uptime_sec": 86400}' in res_success["output"]
    assert mock_queue.enqueue.called
    dispatched_prompt = mock_queue.enqueue.call_args[1]["prompt"]
    assert (
        'System Resource Metrics for System Resource Metric Calculation: {"status": "healthy", "uptime_sec": 86400}'
        in dispatched_prompt
    )

    # Failure outcome (failing lambda raising exception)
    job_fail = dict(job)
    job_fail["action"] = "lambda args, kwargs: 1 / 0"
    mock_queue.reset_mock()

    res_fail = await execute_python_job(job_fail, daemon_queue=mock_queue)
    await asyncio.sleep(0.01)
    assert res_fail["status"] == "error"
    assert res_fail["return_code"] == 1
    assert "division by zero" in res_fail["error"]
    assert mock_queue.enqueue.called
    dispatched_err_prompt = mock_queue.enqueue.call_args[1]["prompt"]
    assert (
        "CRON ERROR: python job 'System Resource Metric Calculation' failed with return code 1"
        in dispatched_err_prompt
    )
