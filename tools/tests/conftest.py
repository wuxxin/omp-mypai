"""Pytest Configuration and Fixtures for mypai_tools test suite."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from mypai_tools.daemon.api.app import app
from mypai_tools.daemon.queue import EventQueue
from mypai_tools.daemon.session_manager import OMPSessionManager
from mypai_tools.signal_client import SignalClient


class FakeRpcClient:
    """Mock OMP RpcClient for fast unit testing."""

    def __init__(self, **kwargs: Any) -> None:
        self.started = False
        self.prompts_received: list[tuple[str, str]] = []
        self.pid = 12345
        self._process = self

    def poll(self) -> None:
        return None

    def start(self) -> "FakeRpcClient":
        self.started = True
        return self

    def stop(self) -> None:
        self.started = False

    def install_headless_ui(self) -> None:
        pass

    def prompt(self, text: str) -> dict[str, Any]:
        self.prompts_received.append((text, "prompt"))
        return {"status": "ok", "response": f"Echo: {text}"}

    def prompt_and_wait(self, text: str, timeout: float = 120.0) -> "FakeRpcClient":
        self.prompts_received.append((text, "prompt_and_wait"))
        return self

    def require_assistant_text(self) -> str:
        return "Echo Assistant Text"

    def steer(self, text: str) -> dict[str, Any]:
        self.prompts_received.append((text, "steer"))
        return {"status": "ok", "response": f"Steer Echo: {text}"}

    def followup(self, text: str) -> dict[str, Any]:
        self.prompts_received.append((text, "followup"))
        return {"status": "ok", "response": f"Followup Echo: {text}"}

    def follow_up(self, text: str) -> dict[str, Any]:
        return self.followup(text)

    def abort_and_prompt(self, text: str) -> dict[str, Any]:
        self.prompts_received.append((text, "abort_and_prompt"))
        return {"status": "ok", "response": f"Abort Echo: {text}"}


@pytest.fixture
def fake_rpc_client() -> FakeRpcClient:
    return FakeRpcClient()


@pytest.fixture
def daemon_queue() -> EventQueue:
    return EventQueue()


@pytest.fixture
def session_manager(tmp_path, fake_rpc_client) -> OMPSessionManager:
    mgr = OMPSessionManager(project_dir=str(tmp_path), session_name="mypai-test-session")
    mgr.rpc_client = fake_rpc_client
    return mgr


@pytest.fixture
def signal_client() -> SignalClient:
    return SignalClient(
        api_url="http://localhost:50889",
        account="+15550001111",
        allowed_sender="+15559992222",
    )


@pytest.fixture
def test_client(daemon_queue, session_manager, signal_client) -> TestClient:
    app.state.daemon_queue = daemon_queue
    app.state.session_manager = session_manager
    app.state.signal_client = signal_client
    return TestClient(app)
