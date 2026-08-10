"""SQLAlchemy Database Models and Pydantic Schemas for MyPAI Cron Tasks."""

import json
from typing import Any

from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class CronJobModel(Base):
    """SQLAlchemy model for scheduled cron tasks with inlined attributes & telemetry."""

    __tablename__ = "cron_jobs"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
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
