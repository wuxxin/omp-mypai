"""Database session management, SQLite WAL mode, path helpers, and cron normalization."""

import hashlib
import json
import os
from typing import Any

import apscheduler
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from mypai_tools.models import Base

APSCHEDULER_VERSION = getattr(apscheduler, "__version__", "3.0.0")
IS_APSCHEDULER_V4 = APSCHEDULER_VERSION.startswith("4")


def substitute_env_vars(val: Any, extra_vars: dict[str, Any] | None = None) -> Any:
    """Recursively expand #[VARNAME] environment and internal execution variables.

    Supports #[VARNAME] syntax for:
    1. System & Process Environment Variables (e.g. #[HINDSIGHT_API_URL], #[HOME])
    2. Internal Execution Variables (e.g. #[_RETURNCODE], #[_STDOUT], #[_STDERR], #[_STDCOMBINED], #[_RESULT])
    """
    combined_vars: dict[str, Any] = dict(os.environ)
    if extra_vars:
        combined_vars.update(extra_vars)

    if isinstance(val, str):
        expanded = val
        for k, v in combined_vars.items():
            placeholder = f"#[{k}]"
            if placeholder in expanded:
                v_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                expanded = expanded.replace(placeholder, v_str)
        return expanded
    elif isinstance(val, dict):
        return {
            substitute_env_vars(k, extra_vars): substitute_env_vars(v, extra_vars)
            for k, v in val.items()
        }
    elif isinstance(val, list):
        return [substitute_env_vars(item, extra_vars) for item in val]
    return val


def normalize_cron_expression(expr: str) -> str:
    """Normalize 5-field cron expression for APScheduler version compatibility.

    Standard cron convention:
    0 = Sun, 1 = Mon, 2 = Tue, 3 = Wed, 4 = Thu, 5 = Fri, 6 = Sat, 7 = Sun.

    APScheduler < 4.0 convention:
    0 = Mon, 1 = Tue, 2 = Wed, 3 = Thu, 4 = Fri, 5 = Sat, 6 = Sun.

    On APScheduler < 4.0, transparently remaps day-of-week (0->6, 1->0, 2->1, 3->2, 4->3, 5->4, 6->5, 7->6)
    so users can always supply standard cron syntax (0 = Sunday).
    """
    if IS_APSCHEDULER_V4 or not expr or not isinstance(expr, str):
        return expr

    parts = expr.strip().split()
    if len(parts) != 5:
        return expr

    minute, hour, dom, month, dow = parts

    def remap_token(token: str) -> str:
        mapping = {
            "0": "6",
            "7": "6",
            "1": "0",
            "2": "1",
            "3": "2",
            "4": "3",
            "5": "4",
            "6": "5",
            "sun": "6",
            "mon": "0",
            "tue": "1",
            "wed": "2",
            "thu": "3",
            "fri": "4",
            "sat": "5",
        }
        low = token.lower()
        return mapping.get(low, token)

    if "," in dow:
        subparts = [remap_token(t) for t in dow.split(",")]
        new_dow = ",".join(subparts)
    elif "-" in dow and not dow.startswith("*"):
        range_parts = dow.split("-", 1)
        start = remap_token(range_parts[0])
        end = remap_token(range_parts[1])
        new_dow = f"{start}-{end}"
    else:
        new_dow = remap_token(dow)

    return f"{minute} {hour} {dom} {month} {new_dow}"


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
