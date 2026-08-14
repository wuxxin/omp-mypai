"""Unit tests for AcpDelegationManager process pool and task tracking."""

import asyncio
import time

import pytest
from mypai_tools.acp.manager import AcpDelegationManager


class MockAcpSession:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.session_id = "mock-session-456"
        self.start_time = time.time()
        self._alive = True
        self.process = type("Process", (), {"pid": 9999})()

    def is_alive(self) -> bool:
        return self._alive

    def prompt(self, message: str, mode: str = "default") -> dict:
        return {"status": "success", "output": f"Processed: {message}"}

    def cancel(self) -> dict:
        return {"status": "cancelled"}

    def stop(self) -> None:
        self._alive = False


@pytest.mark.asyncio
async def test_acp_manager_execute_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Test synchronous task execution in AcpDelegationManager."""
    mgr = AcpDelegationManager(agent_dir=str(tmp_path))

    def mock_get_or_create_session(cwd: str) -> MockAcpSession:
        return MockAcpSession(cwd)

    monkeypatch.setattr(mgr, "get_or_create_session", mock_get_or_create_session)

    res = await mgr.execute_task(cwd=str(tmp_path), prompt="Audit security code")
    assert res["status"] == "success"
    assert "Processed: Audit security code" in res["output"]
    assert res["task_id"].startswith("acp-task-")


@pytest.mark.asyncio
async def test_acp_manager_execute_task_async(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Test async task dispatch in AcpDelegationManager."""
    mgr = AcpDelegationManager(agent_dir=str(tmp_path))

    def mock_get_or_create_session(cwd: str) -> MockAcpSession:
        return MockAcpSession(cwd)

    monkeypatch.setattr(mgr, "get_or_create_session", mock_get_or_create_session)

    dispatch_res = await mgr.execute_task_async(
        cwd=str(tmp_path), prompt="Run background scan"
    )
    assert dispatch_res["status"] == "queued"
    task_id = dispatch_res["task_id"]

    await asyncio.sleep(0.05)
    status_res = mgr.get_task_status(task_id)
    assert status_res["task_id"] == task_id
    assert status_res["status"] in ("running", "success")


def test_acp_manager_list_agents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Test listing active ACP worker agents."""
    mgr = AcpDelegationManager(agent_dir=str(tmp_path))
    sess = MockAcpSession(str(tmp_path))
    mgr.sessions[str(tmp_path)] = sess  # type: ignore

    res = mgr.list_agents()
    assert res["status"] == "success"
    assert len(res["workers"]) == 1
    assert res["workers"][0]["cwd"] == str(tmp_path)
