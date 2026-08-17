"""SQLite database models, WAL session management, and Pydantic schemas for MyPAI Daemon."""

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class JobOpts(BaseModel):
    """Configuration options for job execution engines."""

    timeout_sec: int | None = None
    timezone: str = "local"
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    error_on: str | None = None
    disable_on: str | None = None


class JobResult(BaseModel):
    """Result and error routing rules."""

    action: Literal["log", "prompt", "steer", "followup", "abort_and_prompt"] = "log"
    prompt: str = ""
    error_action: Literal["log", "prompt", "steer", "followup", "abort_and_prompt"] = "log"
    error_prompt: str = ""
    channel: str = ""


class CronJobSchema(BaseModel):
    """Canonical Pydantic Schema for Cron Jobs."""

    id: str | None = None
    name: str
    description: str = ""
    cron: str = "now"
    enabled: bool = True
    kind: Literal["omp", "acp", "shell", "python", "http"] = "omp"
    action: str = "prompt"
    args: list[Any] | str = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    opts: JobOpts = Field(default_factory=JobOpts)
    result: JobResult = Field(default_factory=JobResult)

    # Telemetry fields (Read-Only / State Updates)
    total_runs: int = 0
    total_failures: int = 0
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_runtime: float = 0.0
    last_returncode: int = 0
    last_httpcode: int = 0
    last_output: str = ""
    last_error: str = ""
    created_at: str | None = None
    updated_at: str | None = None


def get_default_timeout_for_kind(kind: str) -> int:
    """Return default timeout in seconds based on job execution kind."""
    clean_kind = str(kind or "omp").lower()
    if clean_kind in ("omp", "acp"):
        return 10
    if clean_kind == "python":
        return 5
    if clean_kind == "http":
        return 30
    if clean_kind == "shell":
        return 120
    return 30


class CronJobModel(Base):
    """SQLAlchemy model for scheduled cron tasks with execution telemetry."""

    __tablename__ = "cron_jobs"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True, default="")
    cron = Column(String(255), nullable=False)
    kind = Column(String(32), nullable=False, default="omp")
    action = Column(Text, nullable=False, default="prompt")
    enabled = Column(Boolean, default=True)

    # Serialized parameters
    args = Column(Text, nullable=True, default="[]")
    kwargs = Column(Text, nullable=True, default="{}")
    opts = Column(Text, nullable=True, default="{}")
    result = Column(Text, nullable=True, default="{}")

    # Execution telemetry fields
    total_runs = Column(Integer, nullable=False, default=0)
    total_failures = Column(Integer, nullable=False, default=0)
    next_run_at = Column(String(64), nullable=True, default="")
    last_run_at = Column(String(64), nullable=True, default="")
    last_runtime = Column(Float, nullable=True, default=0.0)
    last_returncode = Column(Integer, nullable=True, default=0)
    last_httpcode = Column(Integer, nullable=True, default=0)
    last_output = Column(Text, nullable=True, default="")
    last_error = Column(Text, nullable=True, default="")

    created_at = Column(String(64), nullable=False)
    updated_at = Column(String(64), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        """Convert model instance to dictionary representation with parsed JSON fields."""
        parsed_args = self.args
        if isinstance(parsed_args, str) and parsed_args.strip():
            try:
                parsed_args = json.loads(parsed_args)
            except Exception:  # noqa: BLE001
                pass

        parsed_kwargs = self.kwargs
        if isinstance(parsed_kwargs, str) and parsed_kwargs.strip():
            try:
                parsed_kwargs = json.loads(parsed_kwargs)
            except Exception:  # noqa: BLE001
                parsed_kwargs = {}
        elif not parsed_kwargs:
            parsed_kwargs = {}

        parsed_opts = self.opts
        if isinstance(parsed_opts, str) and parsed_opts.strip():
            try:
                parsed_opts = json.loads(parsed_opts)
            except Exception:  # noqa: BLE001
                parsed_opts = {}
        elif not parsed_opts:
            parsed_opts = {}

        parsed_result = self.result
        if isinstance(parsed_result, str) and parsed_result.strip():
            try:
                parsed_result = json.loads(parsed_result)
            except Exception:  # noqa: BLE001
                parsed_result = {}
        elif not parsed_result:
            parsed_result = {}

        # Ensure default timeout is set in opts if absent
        if isinstance(parsed_opts, dict) and parsed_opts.get("timeout_sec") is None:
            parsed_opts["timeout_sec"] = get_default_timeout_for_kind(self.kind)

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "cron": self.cron,
            "kind": self.kind,
            "action": self.action,
            "enabled": bool(self.enabled),
            "args": parsed_args if parsed_args is not None else [],
            "kwargs": parsed_kwargs if isinstance(parsed_kwargs, dict) else {},
            "opts": parsed_opts if isinstance(parsed_opts, dict) else {},
            "result": parsed_result if isinstance(parsed_result, dict) else {},
            "total_runs": int(self.total_runs or 0),
            "total_failures": int(self.total_failures or 0),
            "next_run_at": self.next_run_at or "",
            "last_run_at": self.last_run_at or "",
            "last_runtime": float(self.last_runtime or 0.0),
            "last_returncode": int(self.last_returncode or 0),
            "last_httpcode": int(self.last_httpcode or 0),
            "last_output": self.last_output or "",
            "last_error": self.last_error or "",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_schema(self) -> CronJobSchema:
        """Convert model instance to validated Pydantic CronJobSchema."""
        data = self.to_dict()
        return CronJobSchema.model_validate(data)


class SettingsModel(Base):
    """SQLAlchemy model for key-value project settings page (session UUID, daemon metadata)."""

    __tablename__ = "project_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)


def find_project_root(path: str) -> str:
    """Find top-most project root containing omp.env or .git starting from path."""
    if not path:
        return path
    real_path = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    normalized = os.path.normpath(real_path)

    curr = normalized
    root_found = None
    while curr and curr != os.path.dirname(curr):
        if os.path.exists(os.path.join(curr, "omp.env")) or os.path.exists(
            os.path.join(curr, ".git")
        ):
            root_found = curr
            break
        curr = os.path.dirname(curr)

    return root_found if root_found else normalized


def resolve_agent_dir(agent_dir: str = "") -> str:
    """Resolve target MYPAI_AGENT_DIR directory path."""
    resolved = agent_dir or os.environ.get("MYPAI_AGENT_DIR", "")
    return find_project_root(resolved)


def get_agent_dir_info(agent_dir: str = "") -> tuple[str, str]:
    """Compute (basedir, shorthash) pair for given agent directory."""
    abs_dir = resolve_agent_dir(agent_dir)
    basedir = os.path.basename(abs_dir) or "workspace"
    shorthash = hashlib.sha256(abs_dir.encode("utf-8")).hexdigest()[:8]
    return basedir, shorthash


def get_agent_dir_hash(agent_dir: str = "") -> str:
    """Compute shorthash for normalized real agent directory path."""
    _, shorthash = get_agent_dir_info(agent_dir)
    return shorthash


def get_project_dir_hash(agent_dir: str = "") -> str:
    """Alias for get_agent_dir_hash."""
    return get_agent_dir_hash(agent_dir)


def get_profile_name(profile: str = "") -> str:
    """Get active OMP profile name from parameter, environment, or default 'mypai'."""
    return profile or os.environ.get("OMP_PROFILE", "mypai")


def get_profile_data_dir(profile: str = "") -> str:
    """Get the target data directory for omp-mypai in the active profile."""
    prof = get_profile_name(profile)
    if prof and prof != "default":
        return os.path.expanduser(f"~/.omp/profiles/{prof}/data/omp-mypai")
    return os.path.expanduser("~/.omp/data/omp-mypai")


def get_agent_db_path(agent_dir: str = "", profile: str = "") -> str:
    """Get absolute SQLite database path for given MYPAI_AGENT_DIR in profile directory."""
    basedir, shorthash = get_agent_dir_info(agent_dir)
    plugin_data = os.environ.get(
        "MYPAI_PLUGIN_DATA",
        get_profile_data_dir(profile),
    )
    daemon_db_dir = os.path.join(plugin_data, "daemon")
    os.makedirs(daemon_db_dir, exist_ok=True)
    return os.path.join(daemon_db_dir, f"agent-{basedir}-{shorthash}.db")


def get_project_db_path(agent_dir: str = "", profile: str = "") -> str:
    """Alias for get_agent_db_path."""
    return get_agent_db_path(agent_dir, profile=profile)


def get_daemon_pid_path(agent_dir: str = "", profile: str = "") -> str:
    """Get daemon PID file path for given agent directory in profile directory."""
    basedir, shorthash = get_agent_dir_info(agent_dir)
    plugin_data = os.environ.get(
        "MYPAI_PLUGIN_DATA",
        get_profile_data_dir(profile),
    )
    daemon_dir = os.path.join(plugin_data, "daemon")
    os.makedirs(daemon_dir, exist_ok=True)
    return os.path.join(daemon_dir, f"mypai-daemon-{basedir}-{shorthash}.pid")


def is_daemon_running(agent_dir: str = "", profile: str = "") -> bool:
    """Check if daemon process PID exists and is actively running."""
    pid_path = get_daemon_pid_path(agent_dir, profile=profile)
    if not os.path.isfile(pid_path):
        return False
    try:
        with open(pid_path, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


def get_db_session(agent_dir: str = "", profile: str = ""):
    """Create a scoped SQLAlchemy session connected to SQLite database for target MYPAI_AGENT_DIR."""
    db_path = get_agent_db_path(agent_dir, profile=profile)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        conn.execute(text("PRAGMA busy_timeout=30000;"))
        conn.commit()

    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    return Session()


def get_setting(session: Any, key: str, default: str = "") -> str:
    """Read a setting string value from project_settings table."""
    row = session.query(SettingsModel).filter_by(key=key).first()
    return row.value if row and row.value is not None else default


def set_setting(session: Any, key: str, value: str) -> None:
    """Save or update a setting string value in project_settings table."""
    row = session.query(SettingsModel).filter_by(key=key).first()
    if row:
        row.value = value
    else:
        row = SettingsModel(key=key, value=value)
        session.add(row)
    session.commit()


def import_jobs_to_db(session: Any, jobs_list: list[dict[str, Any]]) -> tuple[int, int]:
    """Bulk import or update cron jobs list in SQLite database session with validation."""
    import uuid

    imported_count = 0
    updated_count = 0
    existing_jobs = session.query(CronJobModel).all()
    id_map = {j.id: j for j in existing_jobs}
    name_map = {j.name: j for j in existing_jobs}

    for raw_item in jobs_list:
        if not isinstance(raw_item, dict) or not raw_item.get("name"):
            continue

        item_name = raw_item["name"].strip()
        item_id = raw_item.get("id")
        existing = id_map.get(item_id) if item_id else name_map.get(item_name)

        # Normalize nested opts and result structures
        opts_dict = raw_item.get("opts") if isinstance(raw_item.get("opts"), dict) else {}
        result_dict = raw_item.get("result") if isinstance(raw_item.get("result"), dict) else {}

        kind_val = raw_item.get("kind", "omp")
        if "timeout_sec" not in opts_dict or opts_dict["timeout_sec"] is None:
            opts_dict["timeout_sec"] = get_default_timeout_for_kind(kind_val)

        args_str = json.dumps(raw_item.get("args", []))
        kwargs_str = json.dumps(raw_item.get("kwargs", {}))
        opts_str = json.dumps(opts_dict)
        result_str = json.dumps(result_dict)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if existing:
            existing.description = raw_item.get("description", existing.description or "")
            existing.cron = raw_item.get("cron", existing.cron)
            existing.kind = kind_val
            existing.action = raw_item.get("action", existing.action)
            existing.enabled = raw_item.get("enabled", existing.enabled)
            existing.args = args_str
            existing.kwargs = kwargs_str
            existing.opts = opts_str
            existing.result = result_str
            existing.updated_at = now_iso
            updated_count += 1
        else:
            new_id = item_id or str(uuid.uuid4())[:8]
            job_obj = CronJobModel(
                id=new_id,
                name=item_name,
                description=raw_item.get("description", ""),
                cron=raw_item.get("cron", "now"),
                kind=kind_val,
                action=raw_item.get("action", "prompt"),
                enabled=raw_item.get("enabled", True),
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
            session.add(job_obj)
            imported_count += 1

    session.commit()
    return imported_count, updated_count


def export_jobs_from_db(session: Any) -> list[dict[str, Any]]:
    """Export all cron job records from SQLite database session as dictionary list."""
    return [j.to_dict() for j in session.query(CronJobModel).all()]
