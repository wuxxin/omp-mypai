#!/usr/bin/env python3
"""FastMCP Cron Scheduler Server for MyPAI targeting mypai_daemon REST API via MYPAI_AGENT_URL."""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mypai_cron_mcp")

mcp = FastMCP("cron-scheduler")
DAEMON_URL = os.getenv("MYPAI_AGENT_URL", "http://127.0.0.1:52080")


def _daemon_http_request(
    endpoint: str, method: str = "GET", data: dict[str, Any] | None = None
) -> dict[str, Any] | list[Any]:
    """Helper to issue HTTP REST calls to mypai_daemon API at MYPAI_AGENT_URL."""
    url = f"{DAEMON_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    req_data = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if req_data else {}
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except Exception as e:  # noqa: BLE001
        logger.debug("Daemon API request error on %s %s: %s", method, url, e)
        return {
            "status": "error",
            "error": f"MYPAI_AGENT_URL unreachable ({DAEMON_URL}): {e}",
        }


def validate_cron_expression(cron_str: str) -> None:
    """Validate 5-field cron syntax or 'now' trigger keyword."""
    if not cron_str or not isinstance(cron_str, str):
        raise ValueError("Cron schedule string cannot be empty.")
    cron_clean = cron_str.strip().lower()
    if cron_clean in ("now", "@now", "@once"):
        return
    parts = cron_str.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"Invalid cron expression '{cron_str}'. Expected 5 fields (e.g. '0 8 * * 0' or 'now')."
        )


@mcp.tool()
def cron_add_job(
    name: str,
    cron: str,
    description: str = "",
    kind: str = "omp",
    action: str = "prompt",
    url: str = "",
    args: Any = None,
    kwargs: Any = None,
    result_prompt: str = "",
    result_error_prompt: str = "",
    result_action: str = "ignore",
    result_channel: str = "",
) -> dict[str, Any]:
    """Register a new scheduled task in the agent database via mypai_daemon API."""
    validate_cron_expression(cron)
    payload = {
        "name": name,
        "description": description,
        "cron": cron,
        "kind": kind,
        "action": action,
        "url": url,
        "args": args,
        "kwargs": kwargs,
        "result_prompt": result_prompt,
        "result_error_prompt": result_error_prompt,
        "result_action": result_action,
        "result_channel": result_channel,
    }

    res = _daemon_http_request("api/v1/cron/jobs", method="POST", data=payload)
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


@mcp.tool()
def cron_run_once(
    name: str,
    kind: str = "omp",
    action: str = "prompt",
    url: str = "",
    args: Any = None,
    kwargs: Any = None,
    result_prompt: str = "",
    result_error_prompt: str = "",
    result_action: str = "ignore",
    result_channel: str = "",
) -> dict[str, Any]:
    """Queue or reschedule an immediate one-shot task ('now') via mypai_daemon API."""
    payload = {
        "name": name,
        "cron": "now",
        "kind": kind,
        "action": action,
        "url": url,
        "args": args,
        "kwargs": kwargs,
        "result_prompt": result_prompt,
        "result_error_prompt": result_error_prompt,
        "result_action": result_action,
        "result_channel": result_channel,
    }
    res = _daemon_http_request(
        "api/v1/cron/jobs/run_once",
        method="POST",
        data=payload,
    )
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


@mcp.tool()
def cron_list_jobs(include_disabled: bool = True) -> list[dict[str, Any]] | dict[str, Any]:
    """List registered cron jobs and execution telemetry via mypai_daemon API."""
    res = _daemon_http_request(
        f"api/v1/cron/jobs?include_disabled={include_disabled}"
    )
    return res


@mcp.tool()
def cron_disable_job(job_id: str = "", name: str = "") -> dict[str, Any]:
    """Disable a scheduled cron job via mypai_daemon API."""
    target_id = (job_id or "").strip() or (name or "").strip()
    if not target_id:
        return {"status": "error", "error": "Either 'job_id' or 'name' must be provided to identify target job."}

    res = _daemon_http_request(
        f"api/v1/cron/jobs/{target_id}/disable", method="POST"
    )
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


@mcp.tool()
def cron_enable_job(job_id: str = "", name: str = "") -> dict[str, Any]:
    """Enable a scheduled cron job via mypai_daemon API."""
    target_id = (job_id or "").strip() or (name or "").strip()
    if not target_id:
        return {"status": "error", "error": "Either 'job_id' or 'name' must be provided to identify target job."}

    res = _daemon_http_request(
        f"api/v1/cron/jobs/{target_id}/enable", method="POST"
    )
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


@mcp.tool()
def cron_modify_job(
    job_id: str = "",
    name: str | None = None,
    description: str | None = None,
    cron: str | None = None,
    kind: str | None = None,
    action: str | None = None,
    url: str | None = None,
    args: Any = None,
    kwargs: Any = None,
    result_prompt: str | None = None,
    result_error_prompt: str | None = None,
    result_action: str | None = None,
    result_channel: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Modify parameters of an existing cron job via mypai_daemon API."""
    target_id = (job_id or "").strip()
    if not target_id and name:
        target_id = name.strip()
    if not target_id:
        return {"status": "error", "error": "Either 'job_id' or 'name' must be provided to identify target job."}

    updates: dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if cron is not None:
        validate_cron_expression(cron)
        updates["cron"] = cron
    if kind is not None:
        updates["kind"] = kind
    if action is not None:
        updates["action"] = action
    if url is not None:
        updates["url"] = url
    if args is not None:
        updates["args"] = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "")
    if kwargs is not None:
        updates["kwargs"] = json.dumps(kwargs) if isinstance(kwargs, (dict, list)) else str(kwargs or "")
    if result_prompt is not None:
        updates["result_prompt"] = result_prompt
    if result_error_prompt is not None:
        updates["result_error_prompt"] = result_error_prompt
    if result_action is not None:
        updates["result_action"] = result_action
    if result_channel is not None:
        updates["result_channel"] = result_channel
    if enabled is not None:
        updates["enabled"] = enabled

    res = _daemon_http_request(
        f"api/v1/cron/jobs/{target_id}",
        method="PUT",
        data=updates,
    )
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


@mcp.tool()
def cron_remove_job(job_id: str = "", name: str = "") -> dict[str, Any]:
    """Delete a cron job via mypai_daemon API."""
    target_id = (job_id or "").strip() or (name or "").strip()
    if not target_id:
        return {"status": "error", "error": "Either 'job_id' or 'name' must be provided to identify target job."}

    res = _daemon_http_request(
        f"api/v1/cron/jobs/{target_id}", method="DELETE"
    )
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


@mcp.tool()
def cron_import_jobs(file_path: str) -> dict[str, Any]:
    """Import cron jobs from a YAML or JSON file into mypai_daemon via API."""
    from mypai_tools.utils import load_jobs_file

    try:
        jobs_list = load_jobs_file(file_path)
        imported_count = 0
        updated_count = 0
        existing_res = cron_list_jobs(include_disabled=True)
        if isinstance(existing_res, dict) and "error" in existing_res:
            return existing_res

        existing_jobs = existing_res if isinstance(existing_res, list) else []
        id_map = {j["id"]: j for j in existing_jobs if isinstance(j, dict) and "id" in j}
        name_map = {j["name"]: j for j in existing_jobs if isinstance(j, dict) and "name" in j}

        for item in jobs_list:
            if not (isinstance(item, dict) and item.get("name") and item.get("cron")):
                continue

            item_id = item.get("id")
            item_name = item.get("name")
            existing = None

            if item_id and item_id in id_map:
                existing = id_map[item_id]
            elif item_name and item_name in name_map:
                existing = name_map[item_name]

            if existing:
                cron_modify_job(
                    job_id=existing["id"],
                    name=item_name,
                    description=item.get("description", existing.get("description", "")),
                    cron=item.get("cron", existing.get("cron", "")),
                    kind=item.get("kind", existing.get("kind", "omp")),
                    action=item.get("action", existing.get("action", "prompt")),
                    url=item.get("url", existing.get("url", "")),
                    args=item.get("args", existing.get("args")),
                    kwargs=item.get("kwargs", existing.get("kwargs")),
                    result_prompt=item.get("result_prompt", existing.get("result_prompt", "")),
                    result_error_prompt=item.get("result_error_prompt", existing.get("result_error_prompt", "")),
                    result_action=item.get("result_action", existing.get("result_action", "ignore")),
                    result_channel=item.get("result_channel", existing.get("result_channel", "")),
                    enabled=item.get("enabled", existing.get("enabled", True)),
                )
                updated_count += 1
            else:
                cron_add_job(
                    name=item_name,
                    description=item.get("description", ""),
                    cron=item["cron"],
                    kind=item.get("kind", "omp"),
                    action=item.get("action", "prompt"),
                    url=item.get("url", ""),
                    args=item.get("args"),
                    kwargs=item.get("kwargs"),
                    result_prompt=item.get("result_prompt", ""),
                    result_error_prompt=item.get("result_error_prompt", ""),
                    result_action=item.get("result_action", "ignore"),
                    result_channel=item.get("result_channel", ""),
                )
                imported_count += 1

        return {
            "status": "imported",
            "imported_count": imported_count,
            "updated_count": updated_count,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def cron_export_jobs(file_path: str = "jobs.yaml", fmt: str | None = None) -> dict[str, Any]:
    """Export all registered cron jobs to a YAML or JSON file via mypai_daemon API (defaults to YAML)."""
    from mypai_tools.utils import dump_jobs_file

    jobs_res = cron_list_jobs(include_disabled=True)
    if isinstance(jobs_res, dict) and "error" in jobs_res:
        return jobs_res
    jobs_list = jobs_res if isinstance(jobs_res, list) else []

    try:
        out_path = dump_jobs_file(file_path, jobs_list, fmt=fmt)
        return {
            "status": "exported",
            "exported_count": len(jobs_list),
            "file_path": out_path,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def cron_enable_execution() -> dict[str, Any]:
    """Temporarily enable global cron task execution in mypai_daemon."""
    res = _daemon_http_request("api/v1/cron/enable", method="POST")
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


@mcp.tool()
def cron_disable_execution() -> dict[str, Any]:
    """Temporarily disable global cron task execution in mypai_daemon."""
    res = _daemon_http_request("api/v1/cron/disable", method="POST")
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


@mcp.tool()
def cron_enable_all_jobs() -> dict[str, Any]:
    """Enable global cron task execution."""
    return cron_enable_execution()


@mcp.tool()
def cron_disable_all_jobs() -> dict[str, Any]:
    """Disable global cron task execution."""
    return cron_disable_execution()


@mcp.tool()
def cron_get_status() -> dict[str, Any]:
    """Get status overview of scheduled cron jobs via mypai_daemon API."""
    res = _daemon_http_request("api/v1/cron/status")
    if isinstance(res, dict):
        return res
    return {"status": "error", "error": f"Unexpected response from daemon: {res}"}


if __name__ == "__main__":
    mcp.run()

