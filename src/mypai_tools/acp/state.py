"""SQLite-backed state persistence for ACP execution ('running', 'suspended', 'shutdown')."""

import logging
from typing import Any

from mypai_tools.persistence import (
    get_db_session,
    get_setting,
    resolve_agent_dir,
    set_setting,
)

logger = logging.getLogger("mypai_daemon.acp.state")

SETTING_KEY_ACP_STATE = "acp_execution_state"
SETTING_KEY_ACP_EXECUTION_ARRAY = "acp_execution_array"
STATE_RUNNING = "running"
STATE_SUSPENDED = "suspended"
STATE_SHUTDOWN = "shutdown"


class AcpState:
    """Manages SQLite settings persistence for ACP intra-agent delegation state and execution history."""

    def __init__(self, agent_dir: str = "") -> None:
        self.agent_dir = resolve_agent_dir(agent_dir)

    def get_state_string(self) -> str:
        """Get raw ACP state string ('running', 'suspended', 'shutdown')."""
        db = get_db_session(self.agent_dir)
        try:
            val = get_setting(db, SETTING_KEY_ACP_STATE, default=STATE_RUNNING)
            return str(val).strip().lower()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error fetching ACP execution state from DB: %s", exc)
            return STATE_RUNNING
        finally:
            db.close()

    def is_running(self) -> bool:
        """Check if ACP delegation is active ('running'). Returns False if 'suspended' or 'shutdown'."""
        return self.get_state_string() == STATE_RUNNING

    def get_status(self) -> dict[str, Any]:
        """Get current state telemetry ('running', 'suspended', 'shutdown')."""
        state_str = self.get_state_string()
        running = state_str == STATE_RUNNING
        return {
            "state": state_str,
            "running": running,
            "suspended": (state_str == STATE_SUSPENDED),
            "shutdown": (state_str == STATE_SHUTDOWN),
            "agent_dir": self.agent_dir,
        }

    def enable(self) -> dict[str, Any]:
        """Enable ACP delegation execution in SQLite settings."""
        db = get_db_session(self.agent_dir)
        try:
            set_setting(db, SETTING_KEY_ACP_STATE, STATE_RUNNING)
            logger.info("ACP execution state set to 'running'.")
            return self.get_status()
        finally:
            db.close()

    def suspend(self) -> dict[str, Any]:
        """Suspend ACP delegation execution in SQLite settings."""
        db = get_db_session(self.agent_dir)
        try:
            set_setting(db, SETTING_KEY_ACP_STATE, STATE_SUSPENDED)
            logger.info("ACP execution state set to 'suspended'.")
            return self.get_status()
        finally:
            db.close()

    def shutdown(self) -> dict[str, Any]:
        """Set ACP execution state to 'shutdown' in SQLite settings."""
        db = get_db_session(self.agent_dir)
        try:
            set_setting(db, SETTING_KEY_ACP_STATE, STATE_SHUTDOWN)
            logger.info("ACP execution state set to 'shutdown'.")
            return self.get_status()
        finally:
            db.close()

    def get_execution_array(self) -> list[dict[str, Any]]:
        """Fetch persistent ACP execution array from SQLite settings."""
        import json

        db = get_db_session(self.agent_dir)
        try:
            val = get_setting(db, SETTING_KEY_ACP_EXECUTION_ARRAY, default="[]")
            if isinstance(val, str) and val.strip():
                parsed = json.loads(val)
                return parsed if isinstance(parsed, list) else []
            if isinstance(val, list):
                return val
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error fetching ACP execution array from DB: %s", exc)
            return []
        finally:
            db.close()

    def set_execution_array(self, tasks: list[dict[str, Any]]) -> None:
        """Save ACP execution array into SQLite settings."""
        import json

        db = get_db_session(self.agent_dir)
        try:
            set_setting(db, SETTING_KEY_ACP_EXECUTION_ARRAY, json.dumps(tasks))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error saving ACP execution array to DB: %s", exc)
        finally:
            db.close()


_acp_state_instances: dict[str, AcpState] = {}


def get_acp_state(agent_dir: str = "") -> AcpState:
    """Get or create singleton AcpState instance for the given agent_dir."""
    resolved = resolve_agent_dir(agent_dir)
    if resolved not in _acp_state_instances:
        _acp_state_instances[resolved] = AcpState(agent_dir=resolved)
    return _acp_state_instances[resolved]
