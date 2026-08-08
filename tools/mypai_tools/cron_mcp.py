#!/usr/bin/env python3
"""MCP tool server for OMP Cron and Task Scheduling.

Uses SQLAlchemy backed SQLite databases per project at:
$HOME/.omp/cron/projects/<project_hash>/cron.db
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, List, Dict, Optional
import uuid

from mcp.server.fastmcp import FastMCP
from sqlalchemy import Boolean, Column, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from apscheduler.triggers.cron import CronTrigger

mcp = FastMCP("cron-scheduler")

Base = declarative_base()

DEFAULT_JOBS_FILE = os.path.join(os.path.dirname(__file__), "default_jobs.json")
VALID_JOB_TYPES = {"rpc", "command", "http"}


class CronJobModel(Base):
    """SQLAlchemy model for scheduled cron jobs."""

    __tablename__ = "cron_jobs"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    cron_expression = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False)
    target_channel = Column(String(64), default="signal")
    job_type = Column(String(32), default="rpc")
    job_action = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(String(64), nullable=False)
    updated_at = Column(String(64), nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "cron_expression": self.cron_expression,
            "prompt": self.prompt,
            "target_channel": self.target_channel,
            "job_type": self.job_type or "rpc",
            "job_action": self.job_action or "",
            "enabled": bool(self.enabled),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def get_project_dir_hash(project_dir: str = "") -> str:
    """Compute 12-char SHA256 hash for normalized project directory path."""
    if not project_dir:
        project_dir = os.getcwd()
    abs_path = os.path.abspath(os.path.expanduser(project_dir))
    return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:12]


def get_project_db_path(project_dir: str = "") -> str:
    """Get absolute SQLite database path for given project directory."""
    p_hash = get_project_dir_hash(project_dir)
    db_dir = os.path.expanduser(f"~/.omp/cron/projects/{p_hash}")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "cron.db")


def get_heartbeat_pid_path(project_dir: str = "") -> str:
    """Get heartbeat daemon PID file path for given project directory."""
    p_hash = get_project_dir_hash(project_dir)
    db_dir = os.path.expanduser(f"~/.omp/cron/projects/{p_hash}")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "heartbeat.pid")


def is_heartbeat_running(project_dir: str = "") -> bool:
    """Check if heartbeat process PID exists and is actively running."""
    pid_path = get_heartbeat_pid_path(project_dir)
    if not os.path.isfile(pid_path):
        return False
    try:
        with open(pid_path, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


def import_default_jobs_if_needed(session) -> None:
    """Import default jobs from default_jobs.json if missing from DB."""
    if not os.path.isfile(DEFAULT_JOBS_FILE):
        return

    try:
        with open(DEFAULT_JOBS_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        hindsight_url = os.getenv("HINDSIGHT_API_URL", "http://localhost:8888")
        hindsight_bank = os.getenv("HINDSIGHT_BANK_ID", "omp-orchestrator")
        omp_rpc_url = os.getenv("OMP_RPC_URL", "http://localhost:51080/v1/rpc")

        content = content.replace("{HINDSIGHT_API_URL}", hindsight_url)
        content = content.replace("{HINDSIGHT_BANK_ID}", hindsight_bank)
        content = content.replace("{OMP_RPC_URL}", omp_rpc_url)

        jobs_data = json.loads(content)
        now_iso = datetime.now(timezone.utc).isoformat()

        for item in jobs_data:
            job_id = item["id"]
            existing = session.query(CronJobModel).filter_by(id=job_id).first()
            if not existing:
                job = CronJobModel(
                    id=job_id,
                    name=item.get("name", "Default Job"),
                    cron_expression=item.get("cron_expression", "* * * * *"),
                    prompt=item.get("prompt", ""),
                    target_channel=item.get("target_channel", "signal"),
                    job_type=item.get("job_type", "rpc"),
                    job_action=item.get("job_action", ""),
                    enabled=item.get("enabled", True),
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                session.add(job)
        session.commit()
    except Exception:
        session.rollback()


def _get_db_session(project_dir: str = ""):
    """Create engine, ensure schema, and seed default jobs for project database."""
    db_path = get_project_db_path(project_dir)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)

    # Ensure schema migration for job_type and job_action if existing DB table lacks them
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT job_type FROM cron_jobs LIMIT 1"))
        except Exception:
            try:
                conn.execute(text("ALTER TABLE cron_jobs ADD COLUMN job_type VARCHAR(32) DEFAULT 'rpc'"))
                conn.execute(text("ALTER TABLE cron_jobs ADD COLUMN job_action TEXT"))
                conn.commit()
            except Exception:
                pass

    Session = sessionmaker(bind=engine)
    session = Session()
    import_default_jobs_if_needed(session)
    return session


def validate_cron_expression(expr: str) -> bool:
    """Validate standard cron expression format using APScheduler CronTrigger."""
    try:
        CronTrigger.from_crontab(expr)
        return True
    except Exception:
        return False


@mcp.tool()
def cron_add_job(
    name: str,
    cron_expression: str,
    prompt: str,
    target_channel: str = "signal",
    job_type: str = "rpc",
    job_action: str = "",
    project_dir: str = "",
) -> Dict[str, Any]:
    """Add a new scheduled cron task backed by per-project SQLite database."""
    if not validate_cron_expression(cron_expression):
        return {
            "error": f"Invalid cron expression '{cron_expression}'. Standard format expected (e.g. '0 8 * * *')."
        }
    if job_type not in VALID_JOB_TYPES:
        return {
            "error": f"Invalid job_type '{job_type}'. Must be one of: {sorted(list(VALID_JOB_TYPES))}."
        }

    session = _get_db_session(project_dir)
    try:
        job_id = str(uuid.uuid4())[:8]
        now_iso = datetime.now(timezone.utc).isoformat()
        job = CronJobModel(
            id=job_id,
            name=name,
            cron_expression=cron_expression,
            prompt=prompt,
            target_channel=target_channel,
            job_type=job_type,
            job_action=job_action,
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
def cron_schedule(
    name: str,
    cron_expression: str,
    prompt: str,
    target_channel: str = "signal",
    job_type: str = "rpc",
    job_action: str = "",
    project_dir: str = "",
) -> Dict[str, Any]:
    """Alias for cron_add_job."""
    return cron_add_job(
        name=name,
        cron_expression=cron_expression,
        prompt=prompt,
        target_channel=target_channel,
        job_type=job_type,
        job_action=job_action,
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
    """List all scheduled cron tasks in project SQLite DB."""
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
    cron_expression: str = "",
    prompt: str = "",
    target_channel: str = "",
    job_type: str = "",
    job_action: str = "",
    project_dir: str = "",
) -> Dict[str, Any]:
    """Modify parameters of an existing scheduled cron task."""
    if cron_expression and not validate_cron_expression(cron_expression):
        return {"error": f"Invalid cron expression '{cron_expression}'."}
    if job_type and job_type not in VALID_JOB_TYPES:
        return {"error": f"Invalid job_type '{job_type}'. Must be one of: {sorted(list(VALID_JOB_TYPES))}."}

    session = _get_db_session(project_dir)
    try:
        job = session.query(CronJobModel).filter_by(id=job_id).first()
        if not job:
            return {"error": f"Job ID '{job_id}' not found."}

        if name:
            job.name = name
        if cron_expression:
            job.cron_expression = cron_expression
        if prompt:
            job.prompt = prompt
        if target_channel:
            job.target_channel = target_channel
        if job_type:
            job.job_type = job_type
        if job_action is not None and job_action != "":
            job.job_action = job_action
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
            cron_expr = item.get("cron_expression") or item.get("schedule") or "* * * * *"
            prompt = item.get("prompt") or ""
            target_channel = item.get("target_channel") or "signal"
            job_type = item.get("job_type") or "rpc"
            job_action = item.get("job_action") or ""
            if isinstance(job_action, (dict, list)):
                job_action = json.dumps(job_action)

            job_id = item.get("id") or str(uuid.uuid4())[:8]
            enabled = bool(item.get("enabled", True))

            existing = session.query(CronJobModel).filter_by(id=job_id).first()
            if existing:
                existing.name = name
                existing.cron_expression = cron_expr
                existing.prompt = prompt
                existing.target_channel = target_channel
                existing.job_type = job_type
                existing.job_action = job_action
                existing.enabled = enabled
                existing.updated_at = now_iso
            else:
                new_job = CronJobModel(
                    id=job_id,
                    name=name,
                    cron_expression=cron_expr,
                    prompt=prompt,
                    target_channel=target_channel,
                    job_type=job_type,
                    job_action=job_action,
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
