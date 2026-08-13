"""Unit tests for the 8 subagent-parity ACP host tools."""

import pytest
from mypai_tools.acp.state import get_acp_state
from mypai_tools.acp.tools import (
    acp_inspect_session,
    acp_list_agents,
    acp_task,
    acp_task_async,
    acp_task_cancel,
    acp_task_result,
    acp_task_status,
    acp_task_steer,
    get_acp_host_tools,
)


def test_get_acp_host_tools_returns_all_8() -> None:
    """Verify get_acp_host_tools returns 8 functions."""
    tools = get_acp_host_tools()
    assert len(tools) == 8


@pytest.mark.asyncio
async def test_acp_tools_blocked_when_suspended(tmp_path: pytest.TempPathFactory) -> None:
    """Verify all 8 host tools return suspension error when state is 'suspended'."""
    agent_dir = str(tmp_path)
    state = get_acp_state(agent_dir)
    state.suspend()

    res_task = await acp_task(cwd=agent_dir, prompt="test", agent_dir=agent_dir)
    assert res_task["status"] == "error"
    assert "suspended" in res_task["error"]

    res_async = await acp_task_async(cwd=agent_dir, prompt="test", agent_dir=agent_dir)
    assert res_async["status"] == "error"
    assert "suspended" in res_async["error"]

    res_status = await acp_task_status(agent_dir=agent_dir)
    assert res_status["status"] == "error"
    assert "suspended" in res_status["error"]

    res_result = await acp_task_result(task_id="t1", agent_dir=agent_dir)
    assert res_result["status"] == "error"
    assert "suspended" in res_result["error"]

    res_steer = await acp_task_steer(task_id="t1", guidance="g", agent_dir=agent_dir)
    assert res_steer["status"] == "error"
    assert "suspended" in res_steer["error"]

    res_cancel = await acp_task_cancel(task_id="t1", agent_dir=agent_dir)
    assert res_cancel["status"] == "error"
    assert "suspended" in res_cancel["error"]

    res_list = await acp_list_agents(agent_dir=agent_dir)
    assert res_list["status"] == "error"
    assert "suspended" in res_list["error"]

    res_inspect = await acp_inspect_session(session_id="s1", agent_dir=agent_dir)
    assert res_inspect["status"] == "error"
    assert "suspended" in res_inspect["error"]
