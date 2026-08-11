"""Tests for mypai_daemon REST API cron endpoints."""

def test_cron_jobs_crud(test_client, tmp_path) -> None:
    proj_dir = str(tmp_path)

    # 1. Add job
    job_payload = {
        "name": "Test Nightly Task",
        "cron": "0 3 * * *",
        "kind": "shell",
        "action": "echo test",
    }
    res_add = test_client.post(f"/api/v1/cron/jobs?project_dir={proj_dir}", json=job_payload)
    assert res_add.status_code == 200
    data_add = res_add.json()
    assert data_add["status"] == "scheduled"
    job_id = data_add["job"]["id"]

    # 2. List jobs
    res_list = test_client.get(f"/api/v1/cron/jobs?project_dir={proj_dir}")
    assert res_list.status_code == 200
    jobs = res_list.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id

    # 3. Disable job
    res_dis = test_client.post(f"/api/v1/cron/jobs/{job_id}/disable?project_dir={proj_dir}")
    assert res_dis.status_code == 200
    assert res_dis.json()["job"]["enabled"] is False

    # 4. Enable job
    res_en = test_client.post(f"/api/v1/cron/jobs/{job_id}/enable?project_dir={proj_dir}")
    assert res_en.status_code == 200
    assert res_en.json()["job"]["enabled"] is True

    # 5. Delete job
    res_del = test_client.delete(f"/api/v1/cron/jobs/{job_id}?project_dir={proj_dir}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"
