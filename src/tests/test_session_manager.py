"""Tests for mypai_daemon.session_manager OMPSessionManager."""

import pytest
from conftest import FakeRpcClient

from mypai_tools.daemon.session_manager import OMPSessionManager


@pytest.mark.asyncio
async def test_session_manager_fixed_session(tmp_path) -> None:
    fake_client = FakeRpcClient()
    mgr = OMPSessionManager(agent_dir=str(tmp_path))
    mgr.rpc_client = fake_client

    assert mgr.session_name == "mypai_daemon - running"
    assert mgr.agent_dir == str(tmp_path)

    # Test executing a prompt turn
    res = await mgr.execute_turn(prompt="Hello MyPAI", mode="prompt")
    assert res["status"] == "success"
    assert res["session_name"] == "mypai_daemon - running"
    assert "Echo: Hello MyPAI" in res["output"]


@pytest.mark.asyncio
async def test_session_manager_modes(tmp_path) -> None:
    fake_client = FakeRpcClient()
    mgr = OMPSessionManager(agent_dir=str(tmp_path))
    mgr.rpc_client = fake_client

    # Test steer mode
    res_steer = await mgr.execute_turn(prompt="Interrupt now", mode="steer")
    assert res_steer["status"] == "success"
    assert "steer dispatched" in res_steer["output"]

    # Test followup mode
    res_followup = await mgr.execute_turn(prompt="Add extra context", mode="followup")
    assert res_followup["status"] == "success"
    assert "Followup Echo" in res_followup["output"]


@pytest.mark.asyncio
async def test_session_manager_get_status(tmp_path) -> None:
    fake_client = FakeRpcClient()
    mgr = OMPSessionManager(agent_dir=str(tmp_path))
    mgr.rpc_client = fake_client

    status = mgr.get_status(queue_depth=2)
    assert status["session_name"] == "mypai_daemon - running"
    assert status["queue_depth"] == 2
    assert status["is_busy"] is False
    assert "model" in status
    assert "model" in status["session_state"]


@pytest.mark.asyncio
async def test_session_manager_abort_updates_last_turn(tmp_path) -> None:
    fake_client = FakeRpcClient()
    mgr = OMPSessionManager(agent_dir=str(tmp_path))
    mgr.rpc_client = fake_client

    # Simulate an active turn in progress
    mgr.is_busy = True
    mgr.active_call = {
        "task_id": "task_active_99",
        "mode": "prompt",
        "model": "qwen3",
        "source": "webui",
        "start_time": 1000.0,
        "prompt_snippet": "Analyze repo structure",
    }

    res = mgr.abort()
    assert res["status"] == "aborted"
    assert mgr.is_busy is False
    assert mgr.active_call is None
    assert mgr.last_turn is not None
    assert mgr.last_turn["task_id"] == "task_active_99"
    assert mgr.last_turn["status"] == "aborted"
    assert mgr.last_turn["model"] == "qwen3"
    assert mgr.last_turn["prompt_snippet"] == "Analyze repo structure"

    status = mgr.get_status()
    assert status["last_turn"]["status"] == "aborted"
    assert status["last_turn"]["task_id"] == "task_active_99"
    assert status["last_turn"]["model"] == "qwen3"
