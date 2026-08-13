"""SQLite-backed state persistence for ACP execution ('running' vs 'suspended')."""

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
STATE_RUNNING = "running"
STATE_SUSPENDED = "suspended"


class AcpState:
    """Manages SQLite settings persistence for ACP intra-agent delegation state."""

    def __init__(self, agent_dir: str = "") -> None:
        self.agent_dir = resolve_agent_dir(agent_dir)

    def is_running(self) -> bool:
        """Check if ACP delegation is active ('running'). Returns False if 'suspended'."""
        db = get_db_session(self.agent_dir)
        try:
            val = get_setting(db, SETTING_KEY_ACP_STATE, default=STATE_RUNNING)
            return str(val).strip().lower() == STATE_RUNNING
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error fetching ACP execution state from DB: %s", exc)
            return True
        finally:
            db.close()

    def get_status(self) -> dict[str, Any]:
        """Get current state telemetry ('running' vs 'suspended')."""
        running = self.is_running()
        return {
            "state": STATE_RUNNING if running else STATE_SUSPENDED,
            "running": running,
            "suspended": not running,
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


_acp_state_instances: dict[str, AcpState] = {}


def get_acp_state(agent_dir: str = "") -> AcpState:
    """Get or create singleton AcpState instance for the given agent_dir."""
    resolved = resolve_agent_dir(agent_dir)
    if resolved not in _acp_state_instances:
        _acp_state_instances[resolved] = AcpState(agent_dir=resolved)
    return _acp_state_instances[resolved]
