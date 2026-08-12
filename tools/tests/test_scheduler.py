"""Tests for mypai_daemon.scheduler CronScheduler."""

import pytest
from mypai_tools.daemon.scheduler import CronScheduler
from mypai_tools.utils import normalize_cron_expression


def test_cron_normalization() -> None:
    # Test Sunday 0 remapped to 6 for APScheduler < 4.0
    assert normalize_cron_expression("0 8 * * 0") == "0 8 * * 6"
    assert normalize_cron_expression("0 8 * * 7") == "0 8 * * 6"
    assert normalize_cron_expression("0 8 * * 1") == "0 8 * * 0"


@pytest.mark.asyncio
async def test_scheduler_shell_job_execution(tmp_path) -> None:
    scheduler = CronScheduler(project_dir=str(tmp_path))
    job = {
        "id": "test_job_1",
        "name": "Echo Test",
        "cron": "now",
        "kind": "shell",
        "action": "echo",
        "args": ["Hello World"],
    }

    res = await scheduler.run_job(job)
    assert res["status"] == "success" or res["return_code"] == 0
    assert "Hello World" in res.get("output", "")
