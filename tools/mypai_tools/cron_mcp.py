#!/usr/bin/env python3
"""FastMCP Cron Scheduler Server for MyPAI targeting mypai_daemon REST API."""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from mypai_tools.persistence import CronJobModel, get_db_session, is_daemon_running

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mypai_cron_mcp")

mcp = FastMCP("cron-scheduler")
DAEMON_URL = os.getenv("MYPAI_DAEMON_URL", "http://127.0.0.1:52080")


def _effective_project_dir(project_dir: str = "") -> str:
    """Resolve project directory falling back to MYPAI_PROJECT_DIR environment variable or default workspace."""
    return (
        project_dir
        or os.getenv("MYPAI_PROJECT_DIR", "")
        or os.getenv("PROJECT_DIR", "")
        or os.path.expanduser("~/agent-shared/mypai-workspace")
    )


def _daemon_http_request(
    endpoint: str, method: str = "GET", data: dict[str, Any] | None = None
) -> dict[str, Any] | list[Any]:
    """Helper to issue HTTP REST calls to mypai_daemon API."""
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
        return {"error": f"Daemon offline: {e}"}


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
    project_dir: str = "",
) -> dict[str, Any]:
    """Register a new scheduled task in the project database via mypai_daemon API."""
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

    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(
        f"api/v1/cron/jobs?project_dir={eff_dir}", method="POST", data=payload
    )
    if isinstance(res, dict) and "error" not in res:
        return res

    # Fallback to direct SQLite DB session if daemon API is offline
    session = get_db_session(eff_dir)
    import uuid

    job_id = str(uuid.uuid4())[:8]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    args_str = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "")
    kwargs_str = (
        json.dumps(kwargs) if isinstance(kwargs, (dict, list)) else str(kwargs or "")
    )

    db_job = CronJobModel(
        id=job_id,
        name=name,
        description=description,
        cron=cron,
        kind=kind,
        action=action,
        url=url,
        args=args_str,
        kwargs=kwargs_str,
        result_prompt=result_prompt,
        result_error_prompt=result_error_prompt,
        result_action=result_action,
        result_channel=result_channel,
        enabled=True,
        created_at=now_iso,
        updated_at=now_iso,
    )
    try:
        session.add(db_job)
        session.commit()
        running = is_daemon_running(eff_dir)
        cron_clean = str(cron or "").strip().lower()
        if cron_clean in ("now", "@now", "@once"):
            status_msg = (
                "scheduled_once" if running else "scheduled_once_daemon_offline"
            )
        else:
            status_msg = "scheduled" if running else "scheduled_daemon_offline"
        return {
            "status": status_msg,
            "job": db_job.to_dict(),
            "daemon_running": running,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": f"Failed to add job '{name}': {exc}"}
    finally:
        session.close()


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
    project_dir: str = "",
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
    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(
        f"api/v1/cron/jobs/run_once?project_dir={eff_dir}",
        method="POST",
        data=payload,
    )
    if isinstance(res, dict) and "error" not in res:
        return res

    # Fallback to direct SQLite DB session
    session = get_db_session(eff_dir)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args_str = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "")
    kwargs_str = (
        json.dumps(kwargs) if isinstance(kwargs, (dict, list)) else str(kwargs or "")
    )

    try:
        existing = (
            session.query(CronJobModel)
            .filter_by(name=name, kind=kind, action=action)
            .all()
        )
        matching_job = None
        for j in existing:
            if (j.args or "") == args_str and (j.kwargs or "") == kwargs_str:
                matching_job = j
                break

        running = is_daemon_running(eff_dir)

        if matching_job:
            matching_job.cron = "now"
            matching_job.enabled = True
            matching_job.updated_at = now_iso
            session.commit()
            status_msg = "rescheduled" if running else "rescheduled_daemon_offline"
            return {
                "status": status_msg,
                "job": matching_job.to_dict(),
                "daemon_running": running,
            }
    finally:
        session.close()

    return cron_add_job(
        name=name,
        cron="now",
        kind=kind,
        action=action,
        url=url,
        args=args,
        kwargs=kwargs,
        result_prompt=result_prompt,
        result_error_prompt=result_error_prompt,
        result_action=result_action,
        result_channel=result_channel,
        project_dir=eff_dir,
    )


@mcp.tool()
def cron_list_jobs(
    project_dir: str = "", include_disabled: bool = True
) -> list[dict[str, Any]]:
    """List registered cron jobs and execution telemetry."""
    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(
        f"api/v1/cron/jobs?include_disabled={include_disabled}&project_dir={eff_dir}"
    )
    if isinstance(res, list):
        return res

    session = get_db_session(eff_dir)
    try:
        query = session.query(CronJobModel)
        if not include_disabled:
            query = query.filter_by(enabled=True)
        return [j.to_dict() for j in query.all()]
    finally:
        session.close()


@mcp.tool()
def cron_disable_job(job_id: str = "", name: str = "", project_dir: str = "") -> dict[str, Any]:
    """Disable a scheduled cron job, identified by job_id or job name."""
    target_id = (job_id or "").strip() or (name or "").strip()
    if not target_id:
        return {"status": "error", "error": "Either 'job_id' or 'name' must be provided to identify target job."}

    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(
        f"api/v1/cron/jobs/{target_id}/disable?project_dir={eff_dir}", method="POST"
    )
    if isinstance(res, dict) and "error" not in res:
        return res

    session = get_db_session(eff_dir)
    try:
        db_job = session.query(CronJobModel).filter(
            (CronJobModel.id == target_id) | (CronJobModel.name == target_id)
        ).first()
        if not db_job:
            return {"status": "error", "error": f"Job '{target_id}' not found"}
        db_job.enabled = False
        session.commit()
        return {"status": "disabled", "job": db_job.to_dict()}
    finally:
        session.close()


@mcp.tool()
def cron_enable_job(job_id: str = "", name: str = "", project_dir: str = "") -> dict[str, Any]:
    """Enable a scheduled cron job, identified by job_id or job name."""
    target_id = (job_id or "").strip() or (name or "").strip()
    if not target_id:
        return {"status": "error", "error": "Either 'job_id' or 'name' must be provided to identify target job."}

    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(
        f"api/v1/cron/jobs/{target_id}/enable?project_dir={eff_dir}", method="POST"
    )
    if isinstance(res, dict) and "error" not in res:
        return res

    session = get_db_session(eff_dir)
    try:
        db_job = session.query(CronJobModel).filter(
            (CronJobModel.id == target_id) | (CronJobModel.name == target_id)
        ).first()
        if not db_job:
            return {"status": "error", "error": f"Job '{target_id}' not found"}
        db_job.enabled = True
        session.commit()
        return {"status": "enabled", "job": db_job.to_dict()}
    finally:
        session.close()


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
    project_dir: str = "",
) -> dict[str, Any]:
    """Modify parameters of an existing cron job, identified by job_id or job name."""
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

    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(
        f"api/v1/cron/jobs/{target_id}?project_dir={eff_dir}",
        method="PUT",
        data=updates,
    )
    if isinstance(res, dict) and "error" not in res:
        return res

    session = get_db_session(eff_dir)
    try:
        db_job = session.query(CronJobModel).filter(
            (CronJobModel.id == target_id) | (CronJobModel.name == target_id)
        ).first()
        if not db_job:
            return {"status": "error", "error": f"Job '{target_id}' not found"}
        for k, v in updates.items():
            setattr(db_job, k, v)
        session.commit()
        return {"status": "modified", "job": db_job.to_dict()}
    finally:
        session.close()


@mcp.tool()
def cron_remove_job(job_id: str = "", name: str = "", project_dir: str = "") -> dict[str, Any]:
    """Delete a cron job from database, identified by job_id or job name."""
    target_id = (job_id or "").strip() or (name or "").strip()
    if not target_id:
        return {"status": "error", "error": "Either 'job_id' or 'name' must be provided to identify target job."}

    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(
        f"api/v1/cron/jobs/{target_id}?project_dir={eff_dir}", method="DELETE"
    )
    if isinstance(res, dict) and "error" not in res:
        return res

    session = get_db_session(eff_dir)
    try:
        db_job = session.query(CronJobModel).filter(
            (CronJobModel.id == target_id) | (CronJobModel.name == target_id)
        ).first()
        if not db_job:
            return {"status": "error", "error": f"Job '{target_id}' not found"}
        deleted_dict = db_job.to_dict()
        session.delete(db_job)
        session.commit()
        return {"status": "cancelled", "job": deleted_dict}
    finally:
        session.close()


@mcp.tool()
def cron_import_jobs(file_path: str, project_dir: str = "") -> dict[str, Any]:
    """Import cron jobs from a JSON file into project database with idempotent upserts by ID or Name."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(abs_path):
        return {"status": "error", "error": f"Import file '{abs_path}' not found"}

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        jobs_list = data.get("jobs", data) if isinstance(data, dict) else data
        if not isinstance(jobs_list, list):
            return {"status": "error", "error": "Expected list of jobs"}

        imported_count = 0
        updated_count = 0
        existing_jobs = cron_list_jobs(project_dir=project_dir, include_disabled=True)
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
                    project_dir=project_dir,
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
                    project_dir=project_dir,
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
def cron_export_jobs(file_path: str, project_dir: str = "") -> dict[str, Any]:
    """Export all registered cron jobs to a JSON file."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    jobs_list = cron_list_jobs(project_dir=project_dir, include_disabled=True)
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump({"jobs": jobs_list}, f, indent=2)
        return {
            "status": "exported",
            "exported_count": len(jobs_list),
            "file_path": abs_path,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def cron_enable_execution(project_dir: str = "") -> dict[str, Any]:
    """Temporarily enable global cron task execution in mypai_daemon."""
    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(f"api/v1/cron/enable?project_dir={eff_dir}", method="POST")
    if isinstance(res, dict) and "error" not in res:
        return res
    running = is_daemon_running(eff_dir)
    return {"status": "enabled", "cron_execution_enabled": True, "daemon_running": running}


@mcp.tool()
def cron_disable_execution(project_dir: str = "") -> dict[str, Any]:
    """Temporarily disable global cron task execution in mypai_daemon."""
    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(f"api/v1/cron/disable?project_dir={eff_dir}", method="POST")
    if isinstance(res, dict) and "error" not in res:
        return res
    running = is_daemon_running(eff_dir)
    return {"status": "disabled", "cron_execution_enabled": False, "daemon_running": running}


@mcp.tool()
def cron_enable_all_jobs(project_dir: str = "") -> dict[str, Any]:
    """Enable global cron task execution."""
    return cron_enable_execution(project_dir=project_dir)


@mcp.tool()
def cron_disable_all_jobs(project_dir: str = "") -> dict[str, Any]:
    """Disable global cron task execution."""
    return cron_disable_execution(project_dir=project_dir)


@mcp.tool()
def cron_get_status(project_dir: str = "") -> dict[str, Any]:
    """Get status overview of scheduled cron jobs and daemon connectivity."""
    eff_dir = _effective_project_dir(project_dir)
    res = _daemon_http_request(f"api/v1/cron/status?project_dir={eff_dir}")
    if isinstance(res, dict) and "error" not in res:
        return res

    session = get_db_session(eff_dir)
    try:
        all_jobs = session.query(CronJobModel).all()
        enabled_count = sum(1 for j in all_jobs if j.enabled)
        running = is_daemon_running(eff_dir)
        return {
            "status": "active" if running else "daemon_offline",
            "cron_execution_enabled": True,
            "total_jobs": len(all_jobs),
            "enabled_jobs": enabled_count,
            "disabled_jobs": len(all_jobs) - enabled_count,
            "daemon_running": running,
        }
    finally:
        session.close()


if __name__ == "__main__":
    mcp.run()
