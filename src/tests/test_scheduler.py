"""Tests for mypai_daemon.scheduler CronScheduler."""

import pytest

from mypai_tools.daemon.scheduler import CronScheduler
from mypai_tools.tools import normalize_cron_expression


def test_cron_normalization() -> None:
    # Test Sunday 0 remapped to 6 for APScheduler < 4.0
    assert normalize_cron_expression("0 8 * * 0") == "0 8 * * 6"
    assert normalize_cron_expression("0 8 * * 7") == "0 8 * * 6"
    assert normalize_cron_expression("0 8 * * 1") == "0 8 * * 0"


@pytest.mark.asyncio
async def test_scheduler_shell_job_execution(tmp_path) -> None:
    scheduler = CronScheduler(agent_dir=str(tmp_path))
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


def test_project_dir_hash_stability(tmp_path) -> None:
    """Test that get_project_dir_hash produces stable hashes across subfolders and MYPAI_PROJECT_DIR."""
    from mypai_tools.persistence import get_project_db_path, get_project_dir_hash

    # Create dummy project structure with omp.env
    proj_root = tmp_path / "my_project"
    sub_dir = proj_root / "tools" / "subfolder"
    sub_dir.mkdir(parents=True)
    (proj_root / "omp.env").write_text("MYPAI_SESSION_NAME=test\n")

    # Hash computed for root and subfolder must be identical
    hash_root = get_project_dir_hash(str(proj_root))
    hash_sub = get_project_dir_hash(str(sub_dir))
    assert hash_root == hash_sub
    assert get_project_db_path(str(proj_root)) == get_project_db_path(str(sub_dir))
