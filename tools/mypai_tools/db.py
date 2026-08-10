#!/usr/bin/env python3
"""Database session management, SQLite WAL mode, auto-migrations, path helpers, and cron normalization."""

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import apscheduler
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from mypai_tools.models import Base, CronJobModel

APSCHEDULER_VERSION = getattr(apscheduler, "__version__", "3.0.0")
IS_APSCHEDULER_V4 = APSCHEDULER_VERSION.startswith("4")


def substitute_env_vars(val: Any, extra_vars: Optional[Dict[str, Any]] = None) -> Any:
    """Recursively expand #[VARNAME] environment and internal execution variables.

    Supports #[VARNAME] syntax for:
    1. System & Process Environment Variables (e.g. #[HINDSIGHT_API_URL], #[HOME])
    2. Internal Execution Variables (e.g. #[_RETURNCODE], #[_STDOUT], #[_STDERR], #[_STDCOMBINED], #[_RESULT])
    """
    combined_vars: Dict[str, Any] = dict(os.environ)
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


def get_default_jobs_file() -> str:
    """Find default_jobs.json in config/ or current directory."""
    candidates = [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "default_jobs.json",
        ),
        os.path.join(os.path.dirname(__file__), "default_jobs.json"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


DEFAULT_JOBS_FILE = get_default_jobs_file()


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


def import_default_jobs_if_needed(session) -> int:
    """Explicitly import default jobs from default_jobs.json if missing from DB."""
    if not os.path.isfile(DEFAULT_JOBS_FILE):
        return 0

    imported_count = 0
    try:
        with open(DEFAULT_JOBS_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        jobs_data = json.loads(content)
        now_iso = datetime.now(timezone.utc).isoformat()

        for item in jobs_data:
            job_id = item["id"]
            existing = session.query(CronJobModel).filter_by(id=job_id).first()
            if not existing:
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

                job_type_val = item.get("type") or item.get("job_type") or "rpc"
                action_val = item.get("action") or item.get("command") or item.get("code") or "prompt"
                out_prompt_val = item.get("output_prompt") or item.get("prompt") or ""
                cron_val = item.get("cron") or item.get("cron_expression") or "* * * * *"
                out_channel_val = item.get("output_channel") or item.get("target_channel") or ""

                job = CronJobModel(
                    id=job_id,
                    name=item.get("name", "Default Job"),
                    cron=cron_val,
                    output_prompt=out_prompt_val,
                    output_channel=out_channel_val,
                    type=job_type_val,
                    action=action_val,
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
        return imported_count
    except Exception:
        session.rollback()
        return 0


def _get_db_session(project_dir: str = ""):
    """Create engine with SQLite WAL mode, run schema migrations, and return Session.

    Note: default_jobs.json is NOT automatically imported on session creation.
    Use heartbeat CLI --import-defaults or explicit import functions to load default jobs.
    """
    db_path = get_project_db_path(project_dir)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    # Enable WAL mode and 30s busy timeout for concurrent safety
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        conn.execute(text("PRAGMA busy_timeout=30000;"))
        conn.commit()

    Base.metadata.create_all(engine)

    # Schema migration checks for renamed columns
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE cron_jobs RENAME COLUMN cron_expression TO cron"))
            conn.commit()
        except Exception:
            pass

        try:
            conn.execute(text("ALTER TABLE cron_jobs RENAME COLUMN target_channel TO output_channel"))
            conn.commit()
        except Exception:
            pass

        try:
            conn.execute(text("ALTER TABLE cron_jobs RENAME COLUMN job_action TO action"))
            conn.commit()
        except Exception:
            pass

        try:
            conn.execute(text("ALTER TABLE cron_jobs RENAME COLUMN payload TO args"))
            conn.commit()
        except Exception:
            pass

        try:
            conn.execute(text("ALTER TABLE cron_jobs RENAME COLUMN job_type TO type"))
            conn.commit()
        except Exception:
            pass

        try:
            conn.execute(text("ALTER TABLE cron_jobs RENAME COLUMN prompt TO output_prompt"))
            conn.commit()
        except Exception:
            pass

        columns_to_add = [
            ("type", "VARCHAR(32) DEFAULT 'rpc'"),
            ("action", "TEXT DEFAULT 'prompt'"),
            ("cron", "VARCHAR(255) DEFAULT '* * * * *'"),
            ("output_prompt", "TEXT DEFAULT ''"),
            ("output_channel", "VARCHAR(64) DEFAULT ''"),
            ("url", "TEXT DEFAULT ''"),
            ("args", "TEXT DEFAULT ''"),
            ("kwargs", "TEXT DEFAULT ''"),
            ("output_action", "VARCHAR(32) DEFAULT 'ignore'"),
            ("last_start", "VARCHAR(64)"),
            ("last_stop", "VARCHAR(64)"),
            ("last_runtime", "FLOAT DEFAULT 0.0"),
            ("last_returncode", "INTEGER DEFAULT 0"),
            ("last_output", "TEXT DEFAULT ''"),
            ("total_calls", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_type in columns_to_add:
            try:
                conn.execute(text(f"SELECT {col_name} FROM cron_jobs LIMIT 1"))
            except Exception:
                try:
                    conn.execute(text(f"ALTER TABLE cron_jobs ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception:
                    pass

    Session = sessionmaker(bind=engine)
    return Session()
