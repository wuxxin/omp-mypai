"""Tests for mypai_daemon REST API cron endpoints."""

import json
from pathlib import Path
from unittest.mock import patch

from mypai_tools import cron_mcp


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


def _make_http_dispatcher(test_client):
    def dispatcher(
        endpoint: str, method: str = "GET", data: dict | None = None
    ) -> dict:
        url = f"/{endpoint.lstrip('/')}"
        if method.upper() == "GET":
            res = test_client.get(url)
        elif method.upper() == "POST":
            res = test_client.post(url, json=data or {})
        elif method.upper() == "PUT":
            res = test_client.put(url, json=data or {})
        elif method.upper() == "DELETE":
            res = test_client.delete(url)
        else:
            return {"status": "error", "error": f"Unsupported method {method}"}
        if res.status_code == 200:
            return res.json()
        return {"status": "error", "error": f"HTTP {res.status_code}: {res.text}"}

    return dispatcher


def test_default_jobs_import_export_cycle(test_client, tmp_path: Path) -> None:
    """Test importing default_jobs.json (without IDs), exporting, verifying generated IDs, and re-importing without duplicates."""
    default_jobs_path = (
        Path(__file__).parent.parent.parent / "config" / "default_jobs.yaml"
    )
    assert default_jobs_path.exists()

    dispatcher = _make_http_dispatcher(test_client)
    with patch("mypai_tools.cron_mcp._daemon_http_request", side_effect=dispatcher):
        # 1. Import default_jobs.yaml (entries have no IDs) into empty DB
        res_imp = cron_mcp.cron_import_jobs(file_path=str(default_jobs_path))
        assert res_imp["status"] == "imported"
        assert res_imp["imported_count"] == 2

        # 2. List jobs from DB
        jobs_initial = cron_mcp.cron_list_jobs()
        assert len(jobs_initial) == 2

        # 3. Export DB jobs to JSON file
        export_file = tmp_path / "exported_default_jobs.json"
        res_exp = cron_mcp.cron_export_jobs(file_path=str(export_file))
        assert res_exp["status"] == "exported"
        assert res_exp["exported_count"] == 2
        assert export_file.exists()

        # 4. Read exported file and verify all entries have auto-generated IDs and descriptions
        exported_data = json.loads(export_file.read_text(encoding="utf-8"))
        exported_jobs = exported_data.get("jobs", [])
        assert len(exported_jobs) == 2
        for job in exported_jobs:
            assert "id" in job and bool(job["id"])
            assert "description" in job and bool(job["description"])

        # 5. Re-import the exported file with IDs into DB
        res_reimp = cron_mcp.cron_import_jobs(file_path=str(export_file))
        assert res_reimp["status"] == "imported"
        assert res_reimp["updated_count"] == 2

        # 6. Verify total job count remains 2 (no duplicates, replaced/updated existing jobs)
        jobs_final = cron_mcp.cron_list_jobs()
        assert len(jobs_final) == 2
        assert {j["name"] for j in jobs_final} == {j["name"] for j in jobs_initial}


def test_cron_modify_by_name_and_unique_constraint(test_client, tmp_path: Path) -> None:
    """Test modifying job by name lookup and verifying unique name constraint."""
    dispatcher = _make_http_dispatcher(test_client)
    with patch("mypai_tools.cron_mcp._daemon_http_request", side_effect=dispatcher):
        # 1. Add initial job
        res_add = cron_mcp.cron_add_job(
            name="Unique Audit Job",
            description="Initial description",
            cron="0 0 * * *",
        )
        assert res_add["status"] == "scheduled"

        # 2. Modify job by NAME (without passing job_id)
        res_mod = cron_mcp.cron_modify_job(
            name="Unique Audit Job",
            description="Updated description by name lookup",
        )
        assert res_mod["status"] == "modified"
        assert res_mod["job"]["description"] == "Updated description by name lookup"

        # 3. Attempt to add another job with duplicate name
        res_dup = cron_mcp.cron_add_job(
            name="Unique Audit Job",
            description="Duplicate attempt",
            cron="0 12 * * *",
        )
        assert "error" in res_dup or res_dup.get("status") == "error"
