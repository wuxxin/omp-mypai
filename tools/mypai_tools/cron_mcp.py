#!/usr/bin/env python3
"""MCP tool server for OMP Cron and Task Scheduling with inlined attributes.

Uses SQLAlchemy backed SQLite databases per project at:
$HOME/.omp/cron/projects/<project_hash>/cron.db
"""

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, List, Optional
import uuid

from mcp.server.fastmcp import FastMCP
from apscheduler.triggers.cron import CronTrigger

from mypai_tools.db import (
    _get_db_session,
    is_heartbeat_running,
    normalize_cron_expression,
)
from mypai_tools.models import Base, CronJobModel

mcp = FastMCP("cron-scheduler")

VALID_JOB_TYPES = {
    "rpc",
    "http",
    "shell",
    "python",
}


def validate_cron_expression(expr: str) -> bool:
    """Validate cron expression or 'now'/'@once' sentinel keyword."""
    if not expr or not isinstance(expr, str):
        return False
    clean = expr.strip().lower()
    if clean in ("now", "@now", "@once"):
        return True
    try:
        CronTrigger.from_crontab(normalize_cron_expression(expr))
        return True
    except Exception:
        return False


@mcp.tool()
def cron_add_job(
    name: str,
    cron: str = "",
    cron_expression: str = "",
    output_prompt: str = "",
    prompt: str = "",
    type: str = "rpc",
    job_type: str = "",
    action: str = "prompt",
    url: str = "",
    command: str = "",
    code: str = "",
    args: Any = "",
    kwargs: Any = "",
    output_action: str = "ignore",
    output_channel: str = "",
    target_channel: str = "",
    project_dir: str = "",
) -> Dict[str, Any]:
    """Add a new scheduled cron task with inlined parameters backed by per-project SQLite database."""
    actual_cron = cron or cron_expression or "* * * * *"
    if not validate_cron_expression(actual_cron):
        return {
            "error": f"Invalid cron expression '{actual_cron}'. Standard 5-field format or 'now' expected."
        }
    actual_type = (job_type or type or "rpc").lower()
    if actual_type not in VALID_JOB_TYPES:
        return {
            "error": f"Invalid job type '{actual_type}'. Must be one of: {sorted(list(VALID_JOB_TYPES))}."
        }

    actual_action = action or command or code or "prompt"
    actual_output_prompt = output_prompt or prompt or ""
    actual_output_channel = output_channel or target_channel or ""

    args_str = args if isinstance(args, str) else json.dumps(args) if args else ""
    kwargs_str = kwargs if isinstance(kwargs, str) else json.dumps(kwargs) if kwargs else ""

    session = _get_db_session(project_dir)
    try:
        job_id = str(uuid.uuid4())[:8]
        now_iso = datetime.now(timezone.utc).isoformat()
        job = CronJobModel(
            id=job_id,
            name=name,
            cron=actual_cron,
            output_prompt=actual_output_prompt,
            output_channel=actual_output_channel,
            type=actual_type,
            action=actual_action,
            url=url,
            args=args_str,
            kwargs=kwargs_str,
            output_action=output_action,
            enabled=True,
            created_at=now_iso,
            updated_at=now_iso,
        )
        session.add(job)
        session.commit()
        job_dict = job.to_dict()

        if not is_heartbeat_running(project_dir):
            return {
                "status": "scheduled_heartbeat_offline",
                "job": job_dict,
                "warning": "Heartbeat daemon is not currently running. Job saved in DB.",
            }
        return {"status": "scheduled", "job": job_dict}
    finally:
        session.close()


@mcp.tool()
def cron_run_once(
    name: str,
    type: str = "rpc",
    job_type: str = "",
    action: str = "prompt",
    url: str = "",
    command: str = "",
    code: str = "",
    args: Any = "",
    kwargs: Any = "",
    output_prompt: str = "",
    prompt: str = "",
    output_action: str = "ignore",
    output_channel: str = "",
    target_channel: str = "",
    project_dir: str = "",
) -> Dict[str, Any]:
    """Execute a task once immediately using 'now' cron trigger.

    If a job with matching (name, type, action, args, kwargs) exists, reschedules it for immediate execution.
    Otherwise, creates a new one-shot job. Upon execution by heartbeat daemon, updates telemetry and disables.
    """
    actual_type = (job_type or type or "rpc").lower()
    if actual_type not in VALID_JOB_TYPES:
        return {
            "error": f"Invalid job type '{actual_type}'. Must be one of: {sorted(list(VALID_JOB_TYPES))}."
        }

    actual_action = action or command or code or "prompt"
    actual_output_prompt = output_prompt or prompt or ""
    actual_output_channel = output_channel or target_channel or ""

    args_str = args if isinstance(args, str) else json.dumps(args) if args else ""
    kwargs_str = kwargs if isinstance(kwargs, str) else json.dumps(kwargs) if kwargs else ""

    session = _get_db_session(project_dir)
    try:
        now_iso = datetime.now(timezone.utc).isoformat()

        # Deduplication check: Search for existing job matching signature
        existing = (
            session.query(CronJobModel)
            .filter_by(
                name=name,
                type=actual_type,
                action=actual_action,
                args=args_str,
                kwargs=kwargs_str,
            )
            .first()
        )

        if existing:
            existing.cron = "now"
            existing.enabled = True
            existing.url = url or existing.url
            if actual_output_prompt:
                existing.output_prompt = actual_output_prompt
            if actual_output_channel:
                existing.output_channel = actual_output_channel
            if output_action != "ignore":
                existing.output_action = output_action
            existing.updated_at = now_iso
            session.commit()
            job_dict = existing.to_dict()
            status_msg = "rescheduled"
        else:
            job_id = str(uuid.uuid4())[:8]
            job = CronJobModel(
                id=job_id,
                name=name,
                cron="now",
                output_prompt=actual_output_prompt,
                output_channel=actual_output_channel,
                type=actual_type,
                action=actual_action,
                url=url,
                args=args_str,
                kwargs=kwargs_str,
                output_action=output_action,
                enabled=True,
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(job)
            session.commit()
            job_dict = job.to_dict()
            status_msg = "scheduled_once"

        if not is_heartbeat_running(project_dir):
            return {
                "status": f"{status_msg}_heartbeat_offline",
                "job": job_dict,
                "warning": "Heartbeat daemon is not currently running. Job saved in DB.",
            }
        return {"status": status_msg, "job": job_dict}
    finally:
        session.close()


@mcp.tool()
def cron_schedule(
    name: str,
    cron: str = "",
    cron_expression: str = "",
    output_prompt: str = "",
    prompt: str = "",
    type: str = "rpc",
    job_type: str = "",
    action: str = "prompt",
    url: str = "",
    command: str = "",
    code: str = "",
    args: Any = "",
    kwargs: Any = "",
    output_action: str = "ignore",
    output_channel: str = "",
    target_channel: str = "",
    project_dir: str = "",
) -> Dict[str, Any]:
    """Alias for cron_add_job."""
    return cron_add_job(
        name=name,
        cron=cron,
        cron_expression=cron_expression,
        output_prompt=output_prompt,
        prompt=prompt,
        type=type,
        job_type=job_type,
        action=action,
        url=url,
        command=command,
        code=code,
        args=args,
        kwargs=kwargs,
        output_action=output_action,
        output_channel=output_channel,
        target_channel=target_channel,
        project_dir=project_dir,
    )


@mcp.tool()
def cron_remove_job(job_id: str, project_dir: str = "") -> Dict[str, Any]:
    """Remove and delete a scheduled cron task by ID."""
    session = _get_db_session(project_dir)
    try:
        job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not job:
            return {"error": f"Job ID '{job_id}' not found."}
        job_dict = job.to_dict()
        session.delete(job)
        session.commit()
        return {"status": "cancelled", "job": job_dict}
    finally:
        session.close()


@mcp.tool()
def cron_cancel(job_id: str, project_dir: str = "") -> Dict[str, Any]:
    """Alias for cron_remove_job."""
    return cron_remove_job(job_id=job_id, project_dir=project_dir)


@mcp.tool()
def cron_pause_job(job_id: str, project_dir: str = "") -> Dict[str, Any]:
    """Pause an active scheduled cron task."""
    session = _get_db_session(project_dir)
    try:
        job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not job:
            return {"error": f"Job ID '{job_id}' not found."}
        job.enabled = False
        job.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return {"status": "paused", "job": job.to_dict()}
    finally:
        session.close()


@mcp.tool()
def cron_resume_job(job_id: str, project_dir: str = "") -> Dict[str, Any]:
    """Resume a paused scheduled cron task."""
    session = _get_db_session(project_dir)
    try:
        job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not job:
            return {"error": f"Job ID '{job_id}' not found."}
        job.enabled = True
        job.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return {"status": "resumed", "job": job.to_dict()}
    finally:
        session.close()


@mcp.tool()
def cron_list_jobs(project_dir: str = "") -> List[Dict[str, Any]]:
    """List all scheduled cron tasks with inlined attributes and telemetry in project SQLite DB."""
    session = _get_db_session(project_dir)
    try:
        jobs = session.query(CronJobModel).all()
        return [j.to_dict() for j in jobs]
    finally:
        session.close()


@mcp.tool()
def cron_list(project_dir: str = "") -> List[Dict[str, Any]]:
    """Alias for cron_list_jobs."""
    return cron_list_jobs(project_dir=project_dir)


@mcp.tool()
def cron_modify_job(
    job_id: str,
    name: str = "",
    cron: str = "",
    cron_expression: str = "",
    output_prompt: str = "",
    prompt: str = "",
    type: str = "",
    job_type: str = "",
    action: str = "",
    url: str = "",
    command: str = "",
    code: str = "",
    args: Any = None,
    kwargs: Any = None,
    output_action: str = "",
    output_channel: str = "",
    target_channel: str = "",
    project_dir: str = "",
) -> Dict[str, Any]:
    """Modify parameters of an existing scheduled cron task."""
    actual_cron = cron or cron_expression or ""
    if actual_cron and not validate_cron_expression(actual_cron):
        return {"error": f"Invalid cron expression '{actual_cron}'."}
    actual_type = (job_type or type or "").lower()
    if actual_type and actual_type not in VALID_JOB_TYPES:
        return {
            "error": f"Invalid job type '{actual_type}'. Must be one of: {sorted(list(VALID_JOB_TYPES))}."
        }

    session = _get_db_session(project_dir)
    try:
        job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not job:
            return {"error": f"Job ID '{job_id}' not found."}

        if name:
            job.name = name
        if actual_cron:
            job.cron = actual_cron
        if output_prompt or prompt:
            job.output_prompt = output_prompt or prompt
        if output_channel or target_channel:
            job.output_channel = output_channel or target_channel
        if actual_type:
            job.type = actual_type
        if action or command or code:
            job.action = action or command or code
        if url:
            job.url = url
        if args is not None:
            job.args = args if isinstance(args, str) else json.dumps(args)
        if kwargs is not None:
            job.kwargs = kwargs if isinstance(kwargs, str) else json.dumps(kwargs)
        if output_action:
            job.output_action = output_action

        job.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return {"status": "modified", "job": job.to_dict()}
    finally:
        session.close()


@mcp.tool()
def cron_import_jobs(file_path: str, project_dir: str = "") -> Dict[str, Any]:
    """Import scheduled cron jobs from JSON file into project SQLite database."""
    abs_file = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(abs_file):
        return {"error": f"Import file '{abs_file}' not found."}

    try:
        with open(abs_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return {"error": f"Failed to parse JSON file: {exc}"}

    job_list: List[Dict[str, Any]] = []
    if isinstance(data, list):
        job_list = data
    elif isinstance(data, dict):
        if "jobs" in data:
            if isinstance(data["jobs"], list):
                job_list = data["jobs"]
            elif isinstance(data["jobs"], dict):
                job_list = list(data["jobs"].values())
        else:
            job_list = [data]

    session = _get_db_session(project_dir)
    imported_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        for item in job_list:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or "Imported Job"
            cron_val = item.get("cron") or item.get("cron_expression") or item.get("schedule") or "* * * * *"
            out_prompt = item.get("output_prompt") or item.get("prompt") or ""
            out_channel = item.get("output_channel") or item.get("target_channel") or ""
            job_type = str(item.get("type") or item.get("job_type") or "rpc").lower()
            action = item.get("action") or item.get("command") or item.get("code") or "prompt"

            args_val = item.get("args", "")
            if isinstance(args_val, (dict, list)):
                args_val = json.dumps(args_val)

            kwargs_val = item.get("kwargs", {})
            if isinstance(kwargs_val, str) and kwargs_val.strip().startswith("{"):
                try:
                    kwargs_val = json.loads(kwargs_val)
                except Exception:
                    kwargs_val = {}
            if item.get("headers") and isinstance(kwargs_val, dict) and "headers" not in kwargs_val:
                kwargs_val["headers"] = item["headers"]
            if isinstance(kwargs_val, (dict, list)):
                kwargs_val = json.dumps(kwargs_val)

            job_id = item.get("id") or str(uuid.uuid4())[:8]
            enabled = bool(item.get("enabled", True))

            existing = session.query(CronJobModel).filter_by(id=job_id).first()
            if existing:
                existing.name = name
                existing.cron = cron_val
                existing.output_prompt = out_prompt
                existing.output_channel = out_channel
                existing.type = job_type
                existing.action = action
                existing.url = item.get("url", existing.url)
                existing.args = args_val
                existing.kwargs = kwargs_val
                existing.output_action = item.get("output_action", existing.output_action)
                existing.enabled = enabled
                existing.updated_at = now_iso
            else:
                new_job = CronJobModel(
                    id=job_id,
                    name=name,
                    cron=cron_val,
                    output_prompt=out_prompt,
                    output_channel=out_channel,
                    type=job_type,
                    action=action,
                    url=item.get("url", ""),
                    args=args_val,
                    kwargs=kwargs_val,
                    output_action=item.get("output_action", "ignore"),
                    enabled=enabled,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                session.add(new_job)
            imported_count += 1

        session.commit()
        return {"status": "imported", "imported_count": imported_count}
    finally:
        session.close()


@mcp.tool()
def cron_export_jobs(file_path: str, project_dir: str = "") -> Dict[str, Any]:
    """Export all scheduled cron jobs from project SQLite database to JSON file."""
    abs_file = os.path.abspath(os.path.expanduser(file_path))
    os.makedirs(os.path.dirname(abs_file), exist_ok=True)

    session = _get_db_session(project_dir)
    try:
        jobs = session.query(CronJobModel).all()
        job_dicts = [j.to_dict() for j in jobs]

        with open(abs_file, "w", encoding="utf-8") as f:
            json.dump({"jobs": job_dicts}, f, indent=2)

        return {
            "status": "exported",
            "file_path": abs_file,
            "exported_count": len(job_dicts),
        }
    finally:
        session.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
