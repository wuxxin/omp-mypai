"""Unit tests for refactored MYPAI_AGENT_DIR database path, session UUID reattachment, and session stats endpoint."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mypai_tools.daemon.session_manager import OMPSessionManager, format_human_uptime
from mypai_tools.persistence import (
    get_agent_dir_info,
    get_db_session,
    get_project_db_path,
    get_setting,
    resolve_agent_dir,
    set_setting,
)


def test_agent_dir_hash_and_db_path(tmp_path: Path) -> None:
    """Test resolution of MYPAI_AGENT_DIR and agent-<basedir>-<shorthash>.db path format."""
    agent_dir = str(tmp_path)
    resolved = resolve_agent_dir(agent_dir)
    assert resolved == str(tmp_path)

    basedir, shorthash = get_agent_dir_info(agent_dir)
    assert basedir == tmp_path.name
    assert len(shorthash) == 8

    db_path = get_project_db_path(agent_dir)
    assert "daemon" in db_path
    assert f"agent-{basedir}-{shorthash}.db" in db_path


def test_project_settings_persistence(tmp_path: Path) -> None:
    """Test key-value settings table read/write persistence."""
    agent_dir = str(tmp_path)
    db = get_db_session(agent_dir)
    try:
        # Default value when unset
        val0 = get_setting(db, "session_uuid", default="default-uuid")
        assert val0 == "default-uuid"

        # Save value
        set_setting(db, "session_uuid", "12345678-abcd-ef01-2345-6789abcdef01")

        # Read back value
        val1 = get_setting(db, "session_uuid")
        assert val1 == "12345678-abcd-ef01-2345-6789abcdef01"
    finally:
        db.close()


def test_format_human_uptime() -> None:
    """Test human readable duration formatting."""
    assert format_human_uptime(45) == "45s"
    assert format_human_uptime(125) == "2m 05s"
    assert format_human_uptime(3665) == "1h 01m"


@pytest.mark.asyncio
async def test_session_manager_session_uuid_persistence(tmp_path: Path) -> None:
    """Test session manager saving and reattaching to session_uuid in database."""
    agent_dir = str(tmp_path)

    fake_rpc = MagicMock()
    fake_rpc._process = MagicMock(poll=MagicMock(return_value=None))
    fake_rpc.get_state.return_value = MagicMock(session_id="saved-uuid-9999")

    with patch("mypai_tools.daemon.session_manager.RpcClient") as mock_client_cls:
        mock_client_cls.return_value.start.return_value = fake_rpc

        # 1. Initialize session manager (spawns new session and saves UUID to DB)
        mgr = OMPSessionManager(agent_dir=agent_dir)
        client = mgr.ensure_connected()
        assert client is fake_rpc
        assert mgr.session_uuid == "saved-uuid-9999"
        assert mgr.session_name == "mypai_daemon - running"
        fake_rpc.set_session_name.assert_called_with("mypai_daemon - running")

        # Verify UUID was persisted to project_settings table
        db = get_db_session(agent_dir)
        try:
            saved_in_db = get_setting(db, "session_uuid")
            assert saved_in_db == "saved-uuid-9999"
        finally:
            db.close()

        # 2. Instantiate a second session manager for same agent_dir -> reattaches using saved UUID
        mgr2 = OMPSessionManager(agent_dir=agent_dir)
        client2 = mgr2.ensure_connected()
        assert client2 is fake_rpc
        assert mgr2.session_uuid == "saved-uuid-9999"
        mock_client_cls.assert_called_with(
            extra_args=[
                "--auto-approve",
                "--profile",
                "mypai",
                "--resume",
                "saved-uuid-9999",
            ],
            cwd=agent_dir,
        )


def test_session_stats_api_endpoint(test_client) -> None:
    """Test GET /api/v1/session/stats REST API endpoint."""
    res = test_client.get("/api/v1/session/stats")
    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert "tokens" in data
    assert "cost" in data
    assert "user_messages" in data
    assert "assistant_messages" in data
