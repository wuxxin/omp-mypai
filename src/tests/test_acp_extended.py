"""Extended tests for ACP async task dispatch, TurnQueue callback ingestion, and status telemetry."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from mypai_tools.acp.manager import AcpDelegationManager
from mypai_tools.daemon.api.app import app
from mypai_tools.daemon.api.ws import ConnectionManager
from mypai_tools.daemon.queue import Priority, TurnQueue


class MockAcpSession:
    def __init__(self, cwd: str, will_fail: bool = False) -> None:
        self.cwd = cwd
        self.session_id = "mock-session-ext-1"
        self.start_time = time.time()
        self._alive = True
        self.will_fail = will_fail
        self.process = type("Process", (), {"pid": 8888})()

    def is_alive(self) -> bool:
        return self._alive

    def prompt(self, message: str, mode: str = "default") -> dict:
        if self.will_fail:
            return {"status": "error", "error": f"Failed executing: {message}"}
        return {"status": "success", "output": f"Worker result for: {message}"}

    def cancel(self) -> dict:
        return {"status": "cancelled"}

    def stop(self) -> None:
        self._alive = False


@pytest.mark.asyncio
async def test_acp_async_completion_enqueues_callback_into_turn_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Verify that when an ACP worker task completes, an async completion callback is dispatched to TurnQueue."""
    mgr = AcpDelegationManager(agent_dir=str(tmp_path))
    turn_queue = TurnQueue()
    ws_manager = ConnectionManager()

    mgr.set_daemon_queue(turn_queue)
    mgr.set_ws_manager(ws_manager)

    def mock_get_or_create_session(cwd: str) -> MockAcpSession:
        return MockAcpSession(cwd, will_fail=False)

    monkeypatch.setattr(mgr, "get_or_create_session", mock_get_or_create_session)

    res = await mgr.execute_task_async(
        cwd=str(tmp_path), prompt="Run background migration", agent_profile="default"
    )
    assert res["status"] == "queued"
    task_id = res["task_id"]

    # Wait briefly for the worker thread in ThreadPoolExecutor to complete
    for _ in range(20):
        if turn_queue.depth() > 0:
            break
        await asyncio.sleep(0.05)

    assert turn_queue.depth() > 0
    items = turn_queue.peek_items()
    item = items[0]
    assert item["source"] == "acp_callback"
    assert item["priority"] == Priority.SYSTEM_EVENT
    assert "[ACP Subagent Task Completed]" in item["prompt"]
    assert f"Task ID: {task_id}" in item["prompt"]
    assert "Worker result for:" in item["prompt"]
    assert "Run background migration" in item["prompt"]


@pytest.mark.asyncio
async def test_acp_async_failure_enqueues_error_callback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Verify that failed ACP tasks enqueue an error callback to TurnQueue."""
    mgr = AcpDelegationManager(agent_dir=str(tmp_path))
    turn_queue = TurnQueue()
    mgr.set_daemon_queue(turn_queue)

    def mock_get_or_create_session(cwd: str) -> MockAcpSession:
        return MockAcpSession(cwd, will_fail=True)

    monkeypatch.setattr(mgr, "get_or_create_session", mock_get_or_create_session)

    res = await mgr.execute_task_async(
        cwd=str(tmp_path), prompt="Run failing task", agent_profile="default"
    )
    task_id = res["task_id"]

    for _ in range(20):
        if turn_queue.depth() > 0:
            break
        await asyncio.sleep(0.05)

    assert turn_queue.depth() > 0
    items = turn_queue.peek_items()
    item = items[0]
    assert "[ACP Subagent Task Failed]" in item["prompt"]
    assert f"Task ID: {task_id}" in item["prompt"]
    assert "Failed executing:" in item["prompt"]
    assert "Run failing task" in item["prompt"]


def test_acp_api_status_and_tasks_endpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Test /api/v1/acp/status telemetry containing running_tasks and finished_tasks, and GET /api/v1/acp/tasks/{task_id}."""
    from mypai_tools.acp.manager import get_acp_manager

    app.state.agent_dir = str(tmp_path)
    client = TestClient(app)

    mgr: AcpDelegationManager = get_acp_manager(str(tmp_path))

    # Inject mock tasks into manager
    mgr.tasks["task-running-1"] = {
        "task_id": "task-running-1",
        "cwd": str(tmp_path),
        "prompt": "Ongoing indexing",
        "status": "running",
        "start_time": time.time() - 5,
        "completed_at": None,
        "duration_sec": 5.0,
        "output": None,
        "error": None,
    }
    mgr.tasks["task-done-1"] = {
        "task_id": "task-done-1",
        "cwd": str(tmp_path),
        "prompt": "Completed indexing",
        "status": "completed",
        "start_time": time.time() - 10,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_sec": 8.0,
        "output": "Indexed 150 files successfully",
        "error": None,
    }

    resp = client.get("/api/v1/acp/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running_tasks" in data
    assert "finished_tasks" in data
    assert len(data["running_tasks"]) >= 1
    assert len(data["finished_tasks"]) >= 1

    # Test GET single task
    task_resp = client.get("/api/v1/acp/tasks/task-done-1")
    assert task_resp.status_code == 200
    task_data = task_resp.json()
    assert task_data["task_id"] == "task-done-1"
    assert task_data["output"] == "Indexed 150 files successfully"

    # Test 404 for missing task
    missing_resp = client.get("/api/v1/acp/tasks/nonexistent-xyz")
    assert missing_resp.status_code == 404


def test_acp_startup_attaches_default_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Verify that ensure_default_worker provisions an active session for the workspace directory on startup."""
    from mypai_tools.acp.manager import AcpDelegationManager

    mgr = AcpDelegationManager(agent_dir=str(tmp_path))

    def mock_get_or_create_session(cwd: str) -> MockAcpSession:
        sess = MockAcpSession(cwd, will_fail=False)
        mgr.sessions[cwd] = sess
        return sess

    monkeypatch.setattr(mgr, "get_or_create_session", mock_get_or_create_session)

    # Initial state has 0 sessions
    assert len(mgr.sessions) == 0

    # Calling ensure_default_worker spawns session for tmp_path
    mgr.ensure_default_worker()
    assert str(tmp_path) in mgr.sessions
    agents = mgr.list_agents()
    assert len(agents["workers"]) == 1
    assert agents["workers"][0]["cwd"] == str(tmp_path)
