"""Unit tests for AcpState persistence and status toggles."""

import pytest
from mypai_tools.acp.state import get_acp_state


def test_acp_state_default_running(tmp_path: pytest.TempPathFactory) -> None:
    """Test default ACP execution state is 'running'."""
    state = get_acp_state(str(tmp_path))
    assert state.is_running() is True
    status = state.get_status()
    assert status["state"] == "running"
    assert status["running"] is True


def test_acp_state_toggle_suspend_and_enable(tmp_path: pytest.TempPathFactory) -> None:
    """Test toggling state to 'suspended' and back to 'running'."""
    state = get_acp_state(str(tmp_path))

    suspend_res = state.suspend()
    assert suspend_res["state"] == "suspended"
    assert state.is_running() is False

    enable_res = state.enable()
    assert enable_res["state"] == "running"
    assert state.is_running() is True
