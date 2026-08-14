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
        self._on_turn_end_listeners: list[Any] = []
        self._on_turn_start_listeners: list[Any] = []
        self._on_agent_end_listeners: list[Any] = []
        self._on_message_update_listeners: list[Any] = []
        self.last_assistant_text = ""

    def poll(self) -> None:
        return None

    def start(self) -> "FakeRpcClient":
        self.started = True
        return self

    def stop(self) -> None:
        self.started = False

    def install_headless_ui(self) -> None:
        pass

    def on_turn_end(self, listener: Any) -> None:
        self._on_turn_end_listeners.append(listener)

    def on_turn_start(self, listener: Any) -> None:
        self._on_turn_start_listeners.append(listener)

    def on_agent_end(self, listener: Any) -> None:
        self._on_agent_end_listeners.append(listener)

    def on_message_update(self, listener: Any) -> None:
        self._on_message_update_listeners.append(listener)

    def trigger_turn_end(self, turn_id: str = "t1") -> None:
        class MockTurnEndEvent:
            def __init__(self, tid: str) -> None:
                self.turn_id = tid

        for listener in list(self._on_turn_end_listeners):
            listener(MockTurnEndEvent(turn_id))

    def prompt(self, text: str) -> dict[str, Any]:
        self.prompts_received.append((text, "prompt"))
        self.last_assistant_text = f"Echo: {text}"
        res = {"status": "ok", "response": self.last_assistant_text}
        self.trigger_turn_end()
        return res

    def get_last_assistant_text(self) -> str:
        return self.last_assistant_text

    def steer(self, text: str) -> dict[str, Any]:
        self.prompts_received.append((text, "steer"))
        self.last_assistant_text = f"Steer Echo: {text}"
        res = {"status": "ok", "response": self.last_assistant_text}
        self.trigger_turn_end()
        return res

    def followup(self, text: str) -> dict[str, Any]:
        self.prompts_received.append((text, "followup"))
        self.last_assistant_text = f"Followup Echo: {text}"
        res = {"status": "ok", "response": self.last_assistant_text}
        self.trigger_turn_end()
        return res

    def follow_up(self, text: str) -> dict[str, Any]:
        return self.followup(text)

    def abort_and_prompt(self, text: str) -> dict[str, Any]:
        self.prompts_received.append((text, "abort_and_prompt"))
        self.last_assistant_text = f"Abort Echo: {text}"
        res = {"status": "ok", "response": self.last_assistant_text}
        self.trigger_turn_end()
        return res

    def abort(self) -> dict[str, Any]:
        self.prompts_received.append(("abort", "abort"))
        self.trigger_turn_end()
        return {"status": "aborted"}


@pytest.fixture
def fake_rpc_client() -> FakeRpcClient:
    return FakeRpcClient()


@pytest.fixture
def daemon_queue() -> EventQueue:
    return EventQueue()


@pytest.fixture
def session_manager(tmp_path, fake_rpc_client) -> OMPSessionManager:
    mgr = OMPSessionManager(agent_dir=str(tmp_path))
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
    app.state.agent_dir = session_manager.agent_dir
    app.state.daemon_queue = daemon_queue
    app.state.session_manager = session_manager
    app.state.signal_client = signal_client
    return TestClient(app)
