#!/usr/bin/env python3
"""FastMCP Cron Scheduler Server for MyPAI.

Exposes MCP tools for registering, modifying, listing, enabling, disabling,
and deleting scheduled jobs stored in the per-project SQLite database
($HOME/.omp/cron/projects/<project_hash>/cron.db).
"""

import json
import logging
import os
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from mypai_tools.db import (
    get_db_session,
    is_heartbeat_running,
)
from mypai_tools.models import CronJobModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mypai_cron_mcp")

mcp = FastMCP("cron-scheduler")


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
    type: str = "rpc",
    action: str = "prompt",
    url: str = "",
    args: Any = None,
    kwargs: Any = None,
    output_prompt: str = "",
    output_action: str = "ignore",
    output_channel: str = "",
    project_dir: str = "",
) -> dict[str, Any]:
    """Register a new scheduled task in the project SQLite database.

    Args:
        name: Human-readable task name (e.g. 'Sunday Reflection Sweep')
        cron: Standard 5-field cron expression (e.g. '0 8 * * 0') or 'now' for immediate one-shot execution
        type: Task type ('rpc', 'http', 'shell', 'python')
        action: Command/verb/code to execute (e.g. 'prompt', 'GET', 'echo', lambda snippet)
        url: Target HTTP URL for http job types
        args: Command positional arguments (list or space-separated string)
        kwargs: Command options / request headers / RPC payload parameters
        output_prompt: Prompt template formatted with #[_STDOUT], #[_STDERR], #[_RETURNCODE], #[_RESULT]
        output_action: Action on execution ('ignore', 'prompt', 'steer', 'followup', 'abort_and_prompt')
        output_channel: Delivery channel (e.g. '' for none, 'signal' for Signal messaging)
        project_dir: Target workspace directory path
    """
    validate_cron_expression(cron)
    session = get_db_session(project_dir)

    job_id = str(uuid.uuid4())[:8]
    now_iso = os.popen("date -u +'%Y-%m-%dT%H:%M:%SZ'").read().strip()

    args_str = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "")
    kwargs_str = (
        json.dumps(kwargs) if isinstance(kwargs, (dict, list)) else str(kwargs or "")
    )

    db_job = CronJobModel(
        id=job_id,
        name=name,
        cron=cron,
        type=type,
        action=action,
        url=url,
        args=args_str,
        kwargs=kwargs_str,
        output_prompt=output_prompt,
        output_action=output_action,
        output_channel=output_channel,
        enabled=True,
        created_at=now_iso,
        updated_at=now_iso,
    )

    try:
        session.add(db_job)
        session.commit()

        running = is_heartbeat_running(project_dir)
        status_msg = "scheduled" if running else "scheduled_heartbeat_offline"

        logger.info(
            "Registered cron task '%s' (ID: %s, cron: '%s', heartbeat: %s)",
            name,
            job_id,
            cron,
            "active" if running else "offline",
        )
        return {
            "status": status_msg,
            "job": db_job.to_dict(),
            "heartbeat_running": running,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.error("Failed to add cron job: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


@mcp.tool()
def cron_run_once(
    name: str,
    type: str = "rpc",
    action: str = "prompt",
    url: str = "",
    args: Any = None,
    kwargs: Any = None,
    output_prompt: str = "",
    output_action: str = "ignore",
    output_channel: str = "",
    project_dir: str = "",
) -> dict[str, Any]:
    """Queue or reschedule an immediate one-shot task ('now') in the project SQLite database.

    If an exact matching task (matching name, type, action, args, kwargs) exists,
    it updates the existing entry (setting cron='now' and enabled=True) to reschedule it.

    Args:
        name: Human-readable task name
        type: Task type ('rpc', 'http', 'shell', 'python')
        action: Command/verb/code to execute
        url: Target HTTP URL for http job types
        args: Command positional arguments
        kwargs: Command options / payload parameters
        output_prompt: Result prompt template
        output_action: Action on execution ('ignore', 'prompt', 'steer', 'followup', 'abort_and_prompt')
        output_channel: Delivery channel ('', 'signal')
        project_dir: Target workspace directory path
    """
    session = get_db_session(project_dir)
    now_iso = os.popen("date -u +'%Y-%m-%dT%H:%M:%SZ'").read().strip()

    args_str = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "")
    kwargs_str = (
        json.dumps(kwargs) if isinstance(kwargs, (dict, list)) else str(kwargs or "")
    )

    try:
        # Deduplication search
        existing = (
            session.query(CronJobModel)
            .filter_by(name=name, type=type, action=action)
            .all()
        )
        matching_job = None
        for j in existing:
            j_args = j.args or ""
            j_kwargs = j.kwargs or ""
            if j_args == args_str and j_kwargs == kwargs_str:
                matching_job = j
                break

        if matching_job:
            matching_job.cron = "now"
            matching_job.enabled = True
            matching_job.output_prompt = output_prompt or matching_job.output_prompt
            matching_job.output_action = output_action or matching_job.output_action
            matching_job.output_channel = (
                output_channel or matching_job.output_channel
            )
            matching_job.url = url or matching_job.url
            matching_job.updated_at = now_iso
            session.commit()

            running = is_heartbeat_running(project_dir)
            status_msg = "rescheduled" if running else "rescheduled_heartbeat_offline"

            logger.info("Rescheduled one-shot task '%s' (ID: %s)", name, matching_job.id)
            return {
                "status": status_msg,
                "job": matching_job.to_dict(),
                "heartbeat_running": running,
            }

        # Create new one-shot job
        job_id = str(uuid.uuid4())[:8]
        db_job = CronJobModel(
            id=job_id,
            name=name,
            cron="now",
            type=type,
            action=action,
            url=url,
            args=args_str,
            kwargs=kwargs_str,
            output_prompt=output_prompt,
            output_action=output_action,
            output_channel=output_channel,
            enabled=True,
            created_at=now_iso,
            updated_at=now_iso,
        )
        session.add(db_job)
        session.commit()

        running = is_heartbeat_running(project_dir)
        status_msg = "scheduled_once" if running else "scheduled_once_heartbeat_offline"

        logger.info("Queued new one-shot task '%s' (ID: %s)", name, job_id)
        return {
            "status": status_msg,
            "job": db_job.to_dict(),
            "heartbeat_running": running,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.error("Failed to queue run_once job: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


@mcp.tool()
def cron_list_jobs(
    project_dir: str = "", include_disabled: bool = True
) -> list[dict[str, Any]]:
    """List registered cron jobs and execution telemetry from project SQLite DB."""
    session = get_db_session(project_dir)
    try:
        query = session.query(CronJobModel)
        if not include_disabled:
            query = query.filter_by(enabled=True)
        jobs = query.all()
        return [j.to_dict() for j in jobs]
    finally:
        session.close()


@mcp.tool()
def cron_disable_job(job_id: str, project_dir: str = "") -> dict[str, Any]:
    """Disable a scheduled cron job in the project SQLite database."""
    session = get_db_session(project_dir)
    try:
        db_job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not db_job:
            return {"status": "error", "error": f"Job ID '{job_id}' not found"}
        db_job.enabled = False
        db_job.updated_at = os.popen("date -u +'%Y-%m-%dT%H:%M:%SZ'").read().strip()
        session.commit()
        return {"status": "disabled", "job": db_job.to_dict()}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


@mcp.tool()
def cron_enable_job(job_id: str, project_dir: str = "") -> dict[str, Any]:
    """Enable a scheduled cron job in the project SQLite database."""
    session = get_db_session(project_dir)
    try:
        db_job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not db_job:
            return {"status": "error", "error": f"Job ID '{job_id}' not found"}
        db_job.enabled = True
        db_job.updated_at = os.popen("date -u +'%Y-%m-%dT%H:%M:%SZ'").read().strip()
        session.commit()
        return {"status": "enabled", "job": db_job.to_dict()}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


# Alias functions for backward compatibility
@mcp.tool()
def cron_pause_job(job_id: str, project_dir: str = "") -> dict[str, Any]:
    """Alias for cron_disable_job."""
    return cron_disable_job(job_id=job_id, project_dir=project_dir)


@mcp.tool()
def cron_resume_job(job_id: str, project_dir: str = "") -> dict[str, Any]:
    """Alias for cron_enable_job."""
    return cron_enable_job(job_id=job_id, project_dir=project_dir)


@mcp.tool()
def cron_modify_job(
    job_id: str,
    name: str | None = None,
    cron: str | None = None,
    type: str | None = None,
    action: str | None = None,
    url: str | None = None,
    args: Any = None,
    kwargs: Any = None,
    output_prompt: str | None = None,
    output_action: str | None = None,
    output_channel: str | None = None,
    enabled: bool | None = None,
    project_dir: str = "",
) -> dict[str, Any]:
    """Modify parameters of an existing cron job in the project SQLite database."""
    session = get_db_session(project_dir)
    try:
        db_job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not db_job:
            return {"status": "error", "error": f"Job ID '{job_id}' not found"}

        if cron is not None:
            validate_cron_expression(cron)
            db_job.cron = cron
        if name is not None:
            db_job.name = name
        if type is not None:
            db_job.type = type
        if action is not None:
            db_job.action = action
        if url is not None:
            db_job.url = url
        if args is not None:
            db_job.args = (
                json.dumps(args) if isinstance(args, (dict, list)) else str(args)
            )
        if kwargs is not None:
            db_job.kwargs = (
                json.dumps(kwargs) if isinstance(kwargs, (dict, list)) else str(kwargs)
            )
        if output_prompt is not None:
            db_job.output_prompt = output_prompt
        if output_action is not None:
            db_job.output_action = output_action
        if output_channel is not None:
            db_job.output_channel = output_channel
        if enabled is not None:
            db_job.enabled = enabled

        db_job.updated_at = os.popen("date -u +'%Y-%m-%dT%H:%M:%SZ'").read().strip()
        session.commit()
        return {"status": "modified", "job": db_job.to_dict()}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


@mcp.tool()
def cron_remove_job(job_id: str, project_dir: str = "") -> dict[str, Any]:
    """Delete a cron job from the project SQLite database."""
    session = get_db_session(project_dir)
    try:
        db_job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not db_job:
            return {"status": "error", "error": f"Job ID '{job_id}' not found"}
        deleted_dict = db_job.to_dict()
        session.delete(db_job)
        session.commit()
        return {"status": "cancelled", "job": deleted_dict}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


@mcp.tool()
def cron_import_jobs(file_path: str, project_dir: str = "") -> dict[str, Any]:
    """Import cron jobs from a JSON file into project SQLite database."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))

    if not os.path.isfile(abs_path):
        return {"status": "error", "error": f"Import file '{abs_path}' not found"}

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        jobs_data = data.get("jobs", data) if isinstance(data, dict) else data
        if not isinstance(jobs_data, list):
            return {
                "status": "error",
                "error": "Expected list of jobs under 'jobs' key",
            }

        session = get_db_session(project_dir)
        imported_count = 0
        now_iso = os.popen("date -u +'%Y-%m-%dT%H:%M:%SZ'").read().strip()

        for item in jobs_data:
            job_id = item.get("id") or item.get("name", "job")[:8]
            cron_val = item.get("cron")
            if not cron_val:
                logger.warning("Skipping job '%s': missing required 'cron' field.", item.get("name"))
                continue

            args_val = item.get("args", "")
            if isinstance(args_val, (dict, list)):
                args_val = json.dumps(args_val)

            kwargs_val = item.get("kwargs", {})
            if isinstance(kwargs_val, (dict, list)):
                kwargs_val = json.dumps(kwargs_val)

            existing = session.query(CronJobModel).filter_by(id=job_id).first()
            if existing:
                existing.name = item.get("name", existing.name)
                existing.cron = cron_val
                existing.output_prompt = item.get("output_prompt", existing.output_prompt)
                existing.output_channel = item.get("output_channel", existing.output_channel)
                existing.type = item.get("type", existing.type)
                existing.action = item.get("action", existing.action)
                existing.url = item.get("url", existing.url)
                existing.args = args_val
                existing.kwargs = kwargs_val
                existing.output_action = item.get("output_action", existing.output_action)
                existing.enabled = item.get("enabled", existing.enabled)
                existing.updated_at = now_iso
            else:
                job = CronJobModel(
                    id=job_id,
                    name=item.get("name", "Imported Job"),
                    cron=cron_val,
                    output_prompt=item.get("output_prompt", ""),
                    output_channel=item.get("output_channel", ""),
                    type=item.get("type", "rpc"),
                    action=item.get("action", "prompt"),
                    url=item.get("url", ""),
                    args=args_val,
                    kwargs=kwargs_val,
                    output_action=item.get("output_action", "ignore"),
                    enabled=item.get("enabled", True),
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                session.add(job)
            imported_count += 1

        session.commit()
        session.close()

        running = is_heartbeat_running(project_dir)
        return {
            "status": "imported",
            "imported_count": imported_count,
            "heartbeat_running": running,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def cron_export_jobs(file_path: str, project_dir: str = "") -> dict[str, Any]:
    """Export all registered cron jobs from project SQLite database to a JSON file."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    session = get_db_session(project_dir)
    try:
        db_jobs = session.query(CronJobModel).all()
        jobs_list = [j.to_dict() for j in db_jobs]
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
    finally:
        session.close()


if __name__ == "__main__":
    mcp.run()
