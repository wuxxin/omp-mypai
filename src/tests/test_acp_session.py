"""Unit tests for AcpClientSession protocol framing and interaction."""

import pytest

from mypai_tools.acp.session import AcpClientSession


def test_acp_session_initialization() -> None:
    """Test initializing an AcpClientSession object."""
    session = AcpClientSession(cwd="/tmp/test_acp_workspace")
    assert session.cwd == "/tmp/test_acp_workspace"
    assert session.process is None
    assert session.is_alive() is False


def test_acp_session_start_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test start fallback when omp binary is not spawning a full server in mock environment."""
    session = AcpClientSession(cwd="/tmp/test_acp_workspace")

    # Mock _send_request to simulate JSON-RPC responses
    def mock_send_request(method: str, params: dict | None = None) -> dict:
        if method == "initialize":
            return {"protocolVersion": "2024-11-05"}
        if method == "session/new":
            return {"sessionId": "test-session-123"}
        if method == "session/prompt":
            return {"text": "Subagent response text"}
        if method == "session/cancel":
            return {"cancelled": True}
        return {}

    monkeypatch.setattr(session, "_send_request", mock_send_request)
    session.process = object()  # type: ignore # Mock running process
    monkeypatch.setattr(session, "is_alive", lambda: True)

    session._initialize_handshake()
    assert session.session_id == "test-session-123"

    res = session.prompt("Hello worker agent")
    assert res["status"] == "success"
    assert res["output"] == "Subagent response text"

    cancel_res = session.cancel()
    assert cancel_res["status"] == "cancelled"
