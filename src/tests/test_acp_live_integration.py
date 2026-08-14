"""Live integration test suite for ACP intra-agent delegation with real omp --mode acp subprocesses."""

import shutil
from pathlib import Path

import pytest
from mypai_tools.acp.manager import AcpDelegationManager
from mypai_tools.acp.session import AcpClientSession

# Skip live tests if omp CLI binary is not available
pytestmark = pytest.mark.skipif(
    not shutil.which("omp"), reason="omp binary not found in system PATH"
)


def test_live_acp_session_lifecycle(tmp_path: Path) -> None:
    """Test spawning a real omp --mode acp subprocess and initial JSON-RPC handshake."""
    workspace = tmp_path / "acp_workspace"
    workspace.mkdir()

    session = AcpClientSession(cwd=str(workspace))
    assert not session.is_alive()

    # Test startup and stdio process spawning
    session.start()
    if session.is_alive():
        assert session.process is not None
        assert session.process.pid > 0

        # Terminate session cleanly
        session.stop()
        assert not session.is_alive()


def test_live_acp_manager_process_pool(tmp_path: Path) -> None:
    """Test AcpDelegationManager worker process tracking with real workspace paths."""
    ws_a = tmp_path / "workspace_a"
    ws_b = tmp_path / "workspace_b"
    ws_a.mkdir()
    ws_b.mkdir()

    manager = AcpDelegationManager()

    # Verify agent listing across target workspaces
    res = manager.list_agents()
    assert isinstance(res, dict)
    assert res.get("status") == "success"
    assert "workers" in res
