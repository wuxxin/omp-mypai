"""Native Host Tools for Cron task management registered into omp_rpc."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from mypai_tools.persistence import (
    CronJobModel,
    export_jobs_from_db,
    get_db_session,
    get_default_timeout_for_kind,
    import_jobs_to_db,
    resolve_agent_dir,
)
from mypai_tools.tools import dump_jobs_file, load_jobs_file

try:
    from omp_rpc import host_tool
except ImportError:
    host_tool = None  # type: ignore

logger = logging.getLogger("mypai_daemon.host_tools.cron")


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


async def cron_add_job_fn(
    name: str,
    cron: str,
    description: str = "",
    kind: str = "omp",
    action: str = "prompt",
    args: Any = None,
    kwargs: Any = None,
    opts: Any = None,
    result: Any = None,
    agent_dir: str = "",
) -> dict[str, Any]:
    """Register a new scheduled task in SQLite database."""
    validate_cron_expression(cron)
    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    job_id = str(uuid.uuid4())[:8]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    opts_dict = opts if isinstance(opts, dict) else {}
    if "timeout_sec" not in opts_dict or opts_dict["timeout_sec"] is None:
        opts_dict["timeout_sec"] = get_default_timeout_for_kind(kind)

    result_dict = result if isinstance(result, dict) else {}
    args_str = json.dumps(args if args is not None else [])
    kwargs_str = json.dumps(kwargs if kwargs is not None else {})
    opts_str = json.dumps(opts_dict)
    result_str = json.dumps(result_dict)

    job_obj = CronJobModel(
        id=job_id,
        name=name.strip(),
        description=description.strip(),
        cron=cron.strip(),
        kind=kind.strip().lower(),
        action=action.strip(),
        enabled=True,
        args=args_str,
        kwargs=kwargs_str,
        opts=opts_str,
        result=result_str,
        total_runs=0,
        total_failures=0,
        next_run_at="",
        last_run_at="",
        last_runtime=0.0,
        last_returncode=0,
        last_httpcode=0,
        last_output="",
        last_error="",
        created_at=now_iso,
        updated_at=now_iso,
    )

    try:
        session.add(job_obj)
        session.commit()
        res = job_obj.to_dict()
        return {"status": "scheduled", "job": res}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


async def cron_run_once_fn(
    name: str,
    kind: str = "omp",
    action: str = "prompt",
    args: Any = None,
    kwargs: Any = None,
    opts: Any = None,
    result: Any = None,
    description: str = "",
    agent_dir: str = "",
) -> dict[str, Any]:
    """Execute an immediate one-shot task ('now')."""
    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        db_job = (
            session.query(CronJobModel)
            .filter((CronJobModel.id == name) | (CronJobModel.name == name))
            .first()
        )
        if db_job:
            db_job.cron = "now"
            db_job.enabled = True
            db_job.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            session.commit()
            return {"status": "scheduled", "job": db_job.to_dict()}
    finally:
        session.close()

    return await cron_add_job_fn(
        name=name,
        cron="now",
        description=description,
        kind=kind,
        action=action,
        args=args,
        kwargs=kwargs,
        opts=opts,
        result=result,
        agent_dir=target_dir,
    )


async def cron_list_jobs_fn(
    include_disabled: bool = True, agent_dir: str = ""
) -> list[dict[str, Any]] | dict[str, Any]:
    """List registered cron jobs and telemetry stats."""
    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        query = session.query(CronJobModel)
        if not include_disabled:
            query = query.filter_by(enabled=True)
        return [j.to_dict() for j in query.all()]
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


async def cron_disable_job_fn(
    job_id: str = "", name: str = "", agent_dir: str = ""
) -> dict[str, Any]:
    """Disable a scheduled cron task."""
    target = (job_id or "").strip() or (name or "").strip()
    if not target:
        return {"status": "error", "error": "Must provide 'job_id' or 'name'."}

    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        db_job = (
            session.query(CronJobModel)
            .filter((CronJobModel.id == target) | (CronJobModel.name == target))
            .first()
        )
        if not db_job:
            return {"status": "error", "error": f"Job '{target}' not found."}
        db_job.enabled = False
        db_job.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        session.commit()
        return {"status": "disabled", "job": db_job.to_dict()}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


async def cron_enable_job_fn(
    job_id: str = "", name: str = "", agent_dir: str = ""
) -> dict[str, Any]:
    """Enable a scheduled cron task."""
    target = (job_id or "").strip() or (name or "").strip()
    if not target:
        return {"status": "error", "error": "Must provide 'job_id' or 'name'."}

    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        db_job = (
            session.query(CronJobModel)
            .filter((CronJobModel.id == target) | (CronJobModel.name == target))
            .first()
        )
        if not db_job:
            return {"status": "error", "error": f"Job '{target}' not found."}
        db_job.enabled = True
        db_job.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        session.commit()
        return {"status": "enabled", "job": db_job.to_dict()}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


async def cron_update_job_fn(
    job_id: str = "",
    name: str | None = None,
    description: str | None = None,
    cron: str | None = None,
    kind: str | None = None,
    action: str | None = None,
    args: Any = None,
    kwargs: Any = None,
    opts: Any = None,
    result: Any = None,
    enabled: bool | None = None,
    agent_dir: str = "",
) -> dict[str, Any]:
    """Modify parameters of an existing cron task."""
    target = (job_id or "").strip() or ((name or "").strip() if name else "")
    if not target:
        return {"status": "error", "error": "Must provide 'job_id' or 'name'."}

    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        db_job = (
            session.query(CronJobModel)
            .filter((CronJobModel.id == target) | (CronJobModel.name == target))
            .first()
        )
        if not db_job:
            return {"status": "error", "error": f"Job '{target}' not found."}

        if name is not None:
            db_job.name = name.strip()
        if description is not None:
            db_job.description = description.strip()
        if cron is not None:
            validate_cron_expression(cron)
            db_job.cron = cron.strip()
        if kind is not None:
            db_job.kind = kind.strip().lower()
        if action is not None:
            db_job.action = action.strip()
        if args is not None:
            db_job.args = json.dumps(args)
        if kwargs is not None:
            db_job.kwargs = json.dumps(kwargs)
        if opts is not None:
            db_job.opts = json.dumps(opts)
        if result is not None:
            db_job.result = json.dumps(result)
        if enabled is not None:
            db_job.enabled = enabled

        db_job.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        session.commit()
        return {"status": "updated", "job": db_job.to_dict()}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


async def cron_delete_job_fn(
    job_id: str = "", name: str = "", agent_dir: str = ""
) -> dict[str, Any]:
    """Delete a cron task from SQLite database."""
    target = (job_id or "").strip() or (name or "").strip()
    if not target:
        return {"status": "error", "error": "Must provide 'job_id' or 'name'."}

    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        db_job = (
            session.query(CronJobModel)
            .filter((CronJobModel.id == target) | (CronJobModel.name == target))
            .first()
        )
        if not db_job:
            return {"status": "error", "error": f"Job '{target}' not found."}
        deleted_data = db_job.to_dict()
        session.delete(db_job)
        session.commit()
        return {"status": "deleted", "job": deleted_data}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


async def cron_import_jobs_fn(file_path: str, agent_dir: str = "") -> dict[str, Any]:
    """Import cron jobs from a YAML or JSON file into SQLite database."""
    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        jobs_list = load_jobs_file(file_path)
        imported_count, updated_count = import_jobs_to_db(session, jobs_list)
        return {
            "status": "imported",
            "imported_count": imported_count,
            "updated_count": updated_count,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


async def cron_export_jobs_fn(
    file_path: str = "jobs.yaml", fmt: str | None = None, agent_dir: str = ""
) -> dict[str, Any]:
    """Export all registered cron jobs to a YAML or JSON file."""
    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        jobs = export_jobs_from_db(session)
        out_path = dump_jobs_file(file_path, jobs, fmt=fmt)
        return {
            "status": "exported",
            "exported_count": len(jobs),
            "file_path": out_path,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


async def cron_global_enable_fn(agent_dir: str = "") -> dict[str, Any]:
    """Enable global cron task execution."""
    return {"status": "enabled", "cron_execution_enabled": True}


async def cron_global_disable_fn(agent_dir: str = "") -> dict[str, Any]:
    """Disable global cron task execution."""
    return {"status": "disabled", "cron_execution_enabled": False}


async def cron_status_fn(agent_dir: str = "") -> dict[str, Any]:
    """Get status overview of scheduled cron tasks."""
    target_dir = resolve_agent_dir(agent_dir)
    session = get_db_session(target_dir)
    try:
        all_jobs = session.query(CronJobModel).all()
        enabled_count = sum(1 for j in all_jobs if j.enabled)
        disabled_count = len(all_jobs) - enabled_count
        return {
            "status": "active" if enabled_count > 0 else "idle",
            "cron_execution_enabled": True,
            "total_jobs": len(all_jobs),
            "enabled_jobs": enabled_count,
            "disabled_jobs": disabled_count,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


def get_cron_host_tools() -> list[Any]:
    """Return tuple/list of all Cron host tools for RpcClient registration."""
    if host_tool is None:
        return [
            cron_add_job_fn,
            cron_run_once_fn,
            cron_list_jobs_fn,
            cron_disable_job_fn,
            cron_enable_job_fn,
            cron_update_job_fn,
            cron_delete_job_fn,
            cron_import_jobs_fn,
            cron_export_jobs_fn,
            cron_global_enable_fn,
            cron_global_disable_fn,
            cron_status_fn,
        ]

    def _wrap_exec(fn: Any) -> Any:
        def _exec(params: Any, ctx: Any = None) -> Any:
            if isinstance(params, dict):
                return fn(**params)
            return fn()

        return _exec

    return [
        host_tool(
            name="add_job",
            description="Register a new scheduled task in the agent SQLite database.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Unique task name"},
                    "cron": {
                        "type": "string",
                        "description": "5-field cron string or 'now'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Human-readable description",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["omp", "acp", "shell", "python", "http"],
                        "default": "omp",
                    },
                    "action": {
                        "type": "string",
                        "description": "Action verb, CLI binary, or Python lambda",
                        "default": "prompt",
                    },
                    "args": {"description": "Positional argument list or target URL"},
                    "kwargs": {"type": "object", "description": "Keyword arguments"},
                    "opts": {"type": "object", "description": "Execution options"},
                    "result": {"type": "object", "description": "Result routing rules"},
                },
                "required": ["name", "cron"],
            },
            execute=_wrap_exec(cron_add_job_fn),
        ),
        host_tool(
            name="run_once",
            description="Queue or execute an immediate one-shot task ('now').",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Task name"},
                    "kind": {
                        "type": "string",
                        "enum": ["omp", "acp", "shell", "python", "http"],
                        "default": "omp",
                    },
                    "action": {"type": "string", "default": "prompt"},
                    "args": {"description": "Positional argument list"},
                    "kwargs": {"type": "object", "description": "Keyword arguments"},
                    "opts": {"type": "object", "description": "Execution options"},
                    "result": {"type": "object", "description": "Result routing rules"},
                },
                "required": ["name"],
            },
            execute=_wrap_exec(cron_run_once_fn),
        ),
        host_tool(
            name="list_jobs",
            description="List registered cron jobs and execution telemetry.",
            parameters={
                "type": "object",
                "properties": {
                    "include_disabled": {
                        "type": "boolean",
                        "description": "Include disabled tasks",
                        "default": True,
                    }
                },
            },
            execute=_wrap_exec(cron_list_jobs_fn),
        ),
        host_tool(
            name="disable_job",
            description="Disable a scheduled cron task.",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Task ID"},
                    "name": {"type": "string", "description": "Task Name"},
                },
            },
            execute=_wrap_exec(cron_disable_job_fn),
        ),
        host_tool(
            name="enable_job",
            description="Enable a scheduled cron task.",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Task ID"},
                    "name": {"type": "string", "description": "Task Name"},
                },
            },
            execute=_wrap_exec(cron_enable_job_fn),
        ),
        host_tool(
            name="update_job",
            description="Modify parameters of an existing cron task.",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Task ID"},
                    "name": {"type": "string", "description": "Task Name"},
                    "description": {"type": "string"},
                    "cron": {"type": "string"},
                    "kind": {"type": "string"},
                    "action": {"type": "string"},
                    "args": {"description": "Positional arguments"},
                    "kwargs": {"type": "object"},
                    "opts": {"type": "object"},
                    "result": {"type": "object"},
                    "enabled": {"type": "boolean"},
                },
            },
            execute=_wrap_exec(cron_update_job_fn),
        ),
        host_tool(
            name="delete_job",
            description="Delete a cron task from SQLite database.",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Task ID"},
                    "name": {"type": "string", "description": "Task Name"},
                },
            },
            execute=_wrap_exec(cron_delete_job_fn),
        ),
        host_tool(
            name="import_jobs",
            description="Import cron jobs from a YAML or JSON file into SQLite database.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to YAML/JSON file",
                    }
                },
                "required": ["file_path"],
            },
            execute=_wrap_exec(cron_import_jobs_fn),
        ),
        host_tool(
            name="export_jobs",
            description="Export all registered cron jobs to a YAML or JSON file.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Output file path (default: jobs.yaml)",
                        "default": "jobs.yaml",
                    },
                    "fmt": {
                        "type": "string",
                        "enum": ["yaml", "json"],
                        "description": "Export format",
                    },
                },
            },
            execute=_wrap_exec(cron_export_jobs_fn),
        ),
        host_tool(
            name="global_enable",
            description="Enable global cron task execution in daemon.",
            parameters={"type": "object", "properties": {}},
            execute=_wrap_exec(cron_global_enable_fn),
        ),
        host_tool(
            name="global_disable",
            description="Disable global cron task execution in daemon.",
            parameters={"type": "object", "properties": {}},
            execute=_wrap_exec(cron_global_disable_fn),
        ),
        host_tool(
            name="status",
            description="Get status overview of scheduled cron tasks.",
            parameters={"type": "object", "properties": {}},
            execute=_wrap_exec(cron_status_fn),
        ),
    ]


add_job = cron_add_job_fn
run_once = cron_run_once_fn
list_jobs = cron_list_jobs_fn
disable_job = cron_disable_job_fn
enable_job = cron_enable_job_fn
update_job = cron_update_job_fn
delete_job = cron_delete_job_fn
import_jobs = cron_import_jobs_fn
export_jobs = cron_export_jobs_fn
global_enable = cron_global_enable_fn
global_disable = cron_global_disable_fn
status = cron_status_fn
