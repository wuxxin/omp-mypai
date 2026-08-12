"""Dedicated unit tests for FastMCP cron_mcp tools interacting with daemon REST API."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from mypai_tools import cron_mcp


def _make_http_dispatcher(test_client: Any):
    """Helper that routes cron_mcp._daemon_http_request through FastAPI TestClient."""

    def dispatcher(endpoint: str, method: str = "GET", data: Any = None) -> Any:
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
            return {"error": f"Unsupported method {method}"}
        if res.status_code == 200:
            return res.json()
        return {"error": f"HTTP {res.status_code}: {res.text}"}

    return dispatcher


def test_cron_mcp_full_http_integration(test_client: Any, tmp_path: Path) -> None:
    """Test all cron_mcp FastMCP tools routed through live daemon REST API endpoints."""
    http_mock = _make_http_dispatcher(test_client)

    with patch("mypai_tools.cron_mcp._daemon_http_request", side_effect=http_mock):
        # 1. Add Job via cron_add_job
        res_add = cron_mcp.cron_add_job(
            name="MCP Scheduled Audit",
            description="Audit tasks via MCP",
            cron="0 2 * * *",
            kind="shell",
            action="echo mcp",
        )
        assert res_add["status"] == "scheduled"
        job_id = res_add["job"]["id"]
        assert job_id is not None

        # 2. List Jobs via cron_list_jobs
        jobs = cron_mcp.cron_list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "MCP Scheduled Audit"
        assert jobs[0]["description"] == "Audit tasks via MCP"

        # 3. Modify Job by NAME via cron_modify_job
        res_mod = cron_mcp.cron_modify_job(
            name="MCP Scheduled Audit",
            description="Updated via MCP name lookup",
        )
        assert res_mod["status"] == "modified"
        assert res_mod["job"]["description"] == "Updated via MCP name lookup"

        # 4. Disable Job by NAME via cron_disable_job
        res_dis = cron_mcp.cron_disable_job(name="MCP Scheduled Audit")
        assert res_dis["status"] == "modified" or res_dis["job"]["enabled"] is False

        # 5. Enable Job by NAME via cron_enable_job
        res_en = cron_mcp.cron_enable_job(name="MCP Scheduled Audit")
        assert res_en["status"] == "modified" or res_en["job"]["enabled"] is True

        # 6. Global Cron Execution Disable via cron_disable_execution
        res_glob_dis = cron_mcp.cron_disable_execution()
        assert res_glob_dis["cron_execution_enabled"] is False

        # 7. Check status via cron_get_status
        res_stat = cron_mcp.cron_get_status()
        assert res_stat["cron_execution_enabled"] is False
        assert res_stat["total_jobs"] == 1

        # 8. Global Cron Execution Enable via cron_enable_execution
        res_glob_en = cron_mcp.cron_enable_execution()
        assert res_glob_en["cron_execution_enabled"] is True

        # 9. Run Once via cron_run_once
        res_once = cron_mcp.cron_run_once(
            name="Immediate One Shot",
            action="echo once",
        )
        assert res_once["status"] == "scheduled"
        assert res_once["job"]["cron"] == "now"

        # 10. Export Jobs via cron_export_jobs
        export_file = tmp_path / "mcp_export.json"
        res_exp = cron_mcp.cron_export_jobs(file_path=str(export_file))
        assert res_exp["status"] == "exported"
        assert export_file.exists()

        # 11. Remove Job by NAME via cron_remove_job
        res_del = cron_mcp.cron_remove_job(name="MCP Scheduled Audit")
        assert res_del["status"] == "deleted"
