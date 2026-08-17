"""Unit tests for native Cron Host Tools."""

from pathlib import Path

import pytest

from mypai_tools.host_tools.cron_tools import (
    cron_add_job_fn,
    cron_delete_job_fn,
    cron_disable_job_fn,
    cron_enable_job_fn,
    cron_export_jobs_fn,
    cron_global_disable_fn,
    cron_global_enable_fn,
    cron_import_jobs_fn,
    cron_list_jobs_fn,
    cron_run_once_fn,
    cron_status_fn,
    cron_update_job_fn,
    get_cron_host_tools,
)


def test_get_cron_host_tools_returns_all_tools() -> None:
    """Verify get_cron_host_tools returns 12 functions."""
    tools = get_cron_host_tools()
    assert len(tools) == 12


@pytest.mark.asyncio
async def test_cron_host_tools_crud(tmp_path: Path) -> None:
    agent_dir = str(tmp_path)

    # 1. Add job
    res_add = await cron_add_job_fn(
        name="Nightly Shell Job",
        cron="0 3 * * *",
        kind="shell",
        action="echo hello",
        description="Test description",
        agent_dir=agent_dir,
    )
    assert res_add["status"] == "scheduled"
    job_id = res_add["job"]["id"]

    # 2. List jobs
    res_list = await cron_list_jobs_fn(agent_dir=agent_dir)
    assert isinstance(res_list, list)
    assert len(res_list) == 1
    assert res_list[0]["id"] == job_id

    # 3. Disable job
    res_dis = await cron_disable_job_fn(job_id=job_id, agent_dir=agent_dir)
    assert res_dis["status"] == "disabled"
    assert res_dis["job"]["enabled"] is False

    # 4. Enable job
    res_en = await cron_enable_job_fn(job_id=job_id, agent_dir=agent_dir)
    assert res_en["status"] == "enabled"
    assert res_en["job"]["enabled"] is True

    # 5. Update job
    res_upd = await cron_update_job_fn(
        job_id=job_id,
        description="Updated description",
        agent_dir=agent_dir,
    )
    assert res_upd["status"] == "updated"
    assert res_upd["job"]["description"] == "Updated description"

    # 6. Status
    res_st = await cron_status_fn(agent_dir=agent_dir)
    assert res_st["status"] == "active"
    assert res_st["total_jobs"] == 1

    # 7. Global enable/disable
    res_g_dis = await cron_global_disable_fn(agent_dir=agent_dir)
    assert res_g_dis["cron_execution_enabled"] is False
    res_g_en = await cron_global_enable_fn(agent_dir=agent_dir)
    assert res_g_en["cron_execution_enabled"] is True

    # 8. Run once
    res_once = await cron_run_once_fn(
        name="Nightly Shell Job",
        agent_dir=agent_dir,
    )
    assert res_once["status"] == "scheduled"

    # 9. Delete job
    res_del = await cron_delete_job_fn(job_id=job_id, agent_dir=agent_dir)
    assert res_del["status"] == "deleted"


@pytest.mark.asyncio
async def test_cron_host_tools_import_export(tmp_path: Path) -> None:
    agent_dir = str(tmp_path)
    example_jobs_path = Path(__file__).parent.parent.parent / "config" / "example_jobs.yaml"
    assert example_jobs_path.exists()

    # Import
    res_imp = await cron_import_jobs_fn(file_path=str(example_jobs_path), agent_dir=agent_dir)
    assert res_imp["status"] == "imported"
    assert res_imp["imported_count"] == 4

    # Export
    export_file = tmp_path / "exported_jobs.yaml"
    res_exp = await cron_export_jobs_fn(file_path=str(export_file), agent_dir=agent_dir)
    assert res_exp["status"] == "exported"
    assert res_exp["exported_count"] == 4
    assert export_file.exists()
