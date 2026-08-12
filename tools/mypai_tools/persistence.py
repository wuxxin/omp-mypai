"""SQLite database models, WAL session management, and PID file path helpers."""

import hashlib
import json
import os
from typing import Any

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


class CronJobModel(Base):
    """SQLAlchemy model for scheduled cron tasks with inlined attributes & telemetry."""

    __tablename__ = "cron_jobs"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True, default="")
    cron = Column(String(255), nullable=False)
    kind = Column(String(32), nullable=False, default="omp")
    action = Column(Text, nullable=False, default="prompt")
    result_action = Column(String(32), nullable=True, default="ignore")
    result_prompt = Column(Text, nullable=True, default="")
    result_error_prompt = Column(Text, nullable=True, default="")
    result_channel = Column(String(64), nullable=True, default="")
    enabled = Column(Boolean, default=True)

    # Inlined executor parameter columns
    url = Column(Text, nullable=True, default="")
    args = Column(Text, nullable=True, default="")
    kwargs = Column(Text, nullable=True, default="")

    # Execution telemetry fields
    last_start = Column(String(64), nullable=True)
    last_stop = Column(String(64), nullable=True)
    last_runtime = Column(Float, nullable=True, default=0.0)
    last_returncode = Column(Integer, nullable=True, default=0)
    last_output = Column(Text, nullable=True, default="")
    total_calls = Column(Integer, nullable=False, default=0)

    created_at = Column(String(64), nullable=False)
    updated_at = Column(String(64), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        """Convert model instance to dictionary representation with parsed JSON args and kwargs."""
        args_data = self.args
        if isinstance(args_data, str) and args_data.strip().startswith(("{", "[")):
            try:
                args_data = json.loads(args_data)
            except Exception:  # noqa: BLE001, S110
                pass

        kwargs_data = self.kwargs
        if isinstance(kwargs_data, str) and kwargs_data.strip().startswith("{"):
            try:
                kwargs_data = json.loads(kwargs_data)
            except Exception:  # noqa: BLE001, S110
                pass

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "cron": self.cron,
            "kind": self.kind,
            "action": self.action,
            "result_prompt": self.result_prompt or "",
            "result_error_prompt": self.result_error_prompt or "",
            "result_channel": self.result_channel or "",
            "enabled": bool(self.enabled),
            "url": self.url or "",
            "args": args_data or "",
            "kwargs": kwargs_data or {},
            "result_action": self.result_action or "ignore",
            "last_start": self.last_start or "",
            "last_stop": self.last_stop or "",
            "last_runtime": float(self.last_runtime or 0.0),
            "last_returncode": int(self.last_returncode or 0),
            "last_output": self.last_output or "",
            "total_calls": int(self.total_calls or 0),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


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
        if os.path.exists(os.path.join(curr, "omp.env")) or os.path.exists(os.path.join(curr, ".git")):
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


def get_project_dir_hash(project_dir: str = "") -> str:
    """Compute 12-char SHA256 hash for normalized real project directory path."""
    _, shorthash = get_agent_dir_info(project_dir)
    return shorthash


def get_project_db_path(project_dir: str = "") -> str:
    """Get absolute SQLite database path for given MYPAI_AGENT_DIR.
    
    Database location format: mypai_plugin_data/daemon/agent-<basedir>-<shorthash>.db
    """
    basedir, shorthash = get_agent_dir_info(project_dir)
    plugin_data = os.environ.get(
        "MYPAI_PLUGIN_DATA",
        os.path.expanduser("~/.omp/data/omp-mypai"),
    )
    daemon_db_dir = os.path.join(plugin_data, "daemon")
    os.makedirs(daemon_db_dir, exist_ok=True)
    return os.path.join(daemon_db_dir, f"agent-{basedir}-{shorthash}.db")


def get_daemon_pid_path(project_dir: str = "") -> str:
    """Get daemon PID file path for given project directory."""
    basedir, shorthash = get_agent_dir_info(project_dir)
    plugin_data = os.environ.get(
        "MYPAI_PLUGIN_DATA",
        os.path.expanduser("~/.omp/data/omp-mypai"),
    )
    daemon_dir = os.path.join(plugin_data, "daemon")
    os.makedirs(daemon_dir, exist_ok=True)
    return os.path.join(daemon_dir, f"mypai-daemon-{basedir}-{shorthash}.pid")


def is_daemon_running(project_dir: str = "") -> bool:
    """Check if daemon process PID exists and is actively running."""
    pid_path = get_daemon_pid_path(project_dir)
    if not os.path.isfile(pid_path):
        return False
    try:
        with open(pid_path, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


def get_db_session(project_dir: str = ""):
    """Create engine with SQLite WAL mode, create database tables, and return Session."""
    db_path = get_project_db_path(project_dir)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    # Enable WAL mode and 30s busy timeout for concurrent safety
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
    """Bulk import or update cron jobs list in SQLite database session."""
    import uuid
    from datetime import datetime, timezone

    imported_count = 0
    updated_count = 0
    existing_jobs = session.query(CronJobModel).all()
    id_map = {j.id: j for j in existing_jobs}
    name_map = {j.name: j for j in existing_jobs}

    for item in jobs_list:
        if not (isinstance(item, dict) and item.get("name") and item.get("cron")):
            continue
        item_id = item.get("id")
        item_name = item.get("name")
        existing = id_map.get(item_id) if item_id else name_map.get(item_name)

        if existing:
            for k in (
                "description",
                "cron",
                "kind",
                "action",
                "url",
                "result_prompt",
                "result_error_prompt",
                "result_action",
                "result_channel",
                "enabled",
            ):
                if k in item:
                    setattr(existing, k, item[k])
            if "args" in item:
                existing.args = (
                    json.dumps(item["args"])
                    if isinstance(item["args"], (dict, list))
                    else str(item["args"] or "")
                )
            if "kwargs" in item:
                existing.kwargs = (
                    json.dumps(item["kwargs"])
                    if isinstance(item["kwargs"], (dict, list))
                    else str(item["kwargs"] or "")
                )
            existing.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            updated_count += 1
        else:
            new_id = item_id or str(uuid.uuid4())[:8]
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            args_str = (
                json.dumps(item.get("args"))
                if isinstance(item.get("args"), (dict, list))
                else str(item.get("args") or "")
            )
            kwargs_str = (
                json.dumps(item.get("kwargs"))
                if isinstance(item.get("kwargs"), (dict, list))
                else str(item.get("kwargs") or "")
            )
            job_obj = CronJobModel(
                id=new_id,
                name=item_name,
                description=item.get("description", ""),
                cron=item["cron"],
                kind=item.get("kind", "omp"),
                action=item.get("action", "prompt"),
                url=item.get("url", ""),
                args=args_str,
                kwargs=kwargs_str,
                result_prompt=item.get("result_prompt", ""),
                result_error_prompt=item.get("result_error_prompt", ""),
                result_action=item.get("result_action", "ignore"),
                result_channel=item.get("result_channel", ""),
                enabled=item.get("enabled", True),
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


