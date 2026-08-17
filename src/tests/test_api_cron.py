"""Tests for mypai_daemon REST API cron endpoints."""

from pathlib import Path


def test_cron_jobs_crud(test_client, tmp_path) -> None:
    # 1. Add job
    job_payload = {
        "name": "Test Nightly Task",
        "cron": "0 3 * * *",
        "kind": "shell",
        "action": "echo test",
    }
    res_add = test_client.post("/api/v1/cron/jobs", json=job_payload)
    assert res_add.status_code == 200
    data_add = res_add.json()
    assert data_add["status"] == "scheduled"
    job_id = data_add["job"]["id"]

    # 2. List jobs
    res_list = test_client.get("/api/v1/cron/jobs")
    assert res_list.status_code == 200
    jobs = res_list.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id

    # 3. Disable job
    res_dis = test_client.post(f"/api/v1/cron/jobs/{job_id}/disable")
    assert res_dis.status_code == 200
    assert res_dis.json()["job"]["enabled"] is False

    # 4. Enable job
    res_en = test_client.post(f"/api/v1/cron/jobs/{job_id}/enable")
    assert res_en.status_code == 200
    assert res_en.json()["job"]["enabled"] is True

    # 5. Disable global execution
    res_dis_all = test_client.post("/api/v1/cron/disable")
    assert res_dis_all.status_code == 200
    assert res_dis_all.json()["cron_execution_enabled"] is False

    # 6. Check cron status
    res_stat = test_client.get("/api/v1/cron/status")
    assert res_stat.status_code == 200
    assert res_stat.json()["cron_execution_enabled"] is False
    assert res_stat.json()["status"] == "disabled"

    # 7. Enable global execution
    res_en_all = test_client.post("/api/v1/cron/enable")
    assert res_en_all.status_code == 200
    assert res_en_all.json()["cron_execution_enabled"] is True

    # 8. Delete job
    res_del = test_client.delete(f"/api/v1/cron/jobs/{job_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"


def test_example_jobs_import_export_cycle(test_client, tmp_path: Path) -> None:
    """Test importing example_jobs.yaml, exporting via API, and re-importing without duplicates."""
    example_jobs_path = Path(__file__).parent.parent.parent / "config" / "example_jobs.yaml"
    assert example_jobs_path.exists()

    from mypai_tools.tools import load_jobs_file

    jobs_data = load_jobs_file(str(example_jobs_path))

    # 1. Import via API
    res_imp = test_client.post("/api/v1/cron/import", json=jobs_data)
    assert res_imp.status_code == 200
    data_imp = res_imp.json()
    assert data_imp["status"] == "imported"
    assert data_imp["imported"] == 4

    # 2. List jobs from API
    res_list = test_client.get("/api/v1/cron/jobs")
    assert res_list.status_code == 200
    jobs_initial = res_list.json()
    assert len(jobs_initial) == 4

    # 3. Export via API
    res_exp = test_client.get("/api/v1/cron/export")
    assert res_exp.status_code == 200
    exported_jobs = res_exp.json()
    assert len(exported_jobs) == 4

    for job in exported_jobs:
        assert "id" in job and bool(job["id"])
        assert "description" in job

    # 4. Re-import the exported file with IDs
    res_reimp = test_client.post("/api/v1/cron/import", json=exported_jobs)
    assert res_reimp.status_code == 200
    data_reimp = res_reimp.json()
    assert data_reimp["status"] == "imported"
    assert data_reimp["updated"] == 4

    # 5. Verify total job count remains 4
    res_final = test_client.get("/api/v1/cron/jobs")
    assert res_final.status_code == 200
    jobs_final = res_final.json()
    assert len(jobs_final) == 4
    assert {j["name"] for j in jobs_final} == {j["name"] for j in jobs_initial}
