"""Host tools for ACP intra-agent asynchronous task delegation."""

import logging
from typing import Any

from mypai_tools.acp.manager import get_acp_manager
from mypai_tools.acp.state import get_acp_state

try:
    from omp_rpc import host_tool
except ImportError:
    host_tool = None  # type: ignore

logger = logging.getLogger("mypai_daemon.acp.tools")


async def acp_task_async_fn(
    cwd: str, prompt: str, agent_profile: str = "", agent_dir: str = ""
) -> dict[str, Any]:
    """Dispatch asynchronous background task to an ACP worker process."""
    if not get_acp_state(agent_dir).is_running():
        return {
            "status": "error",
            "error": "ACP delegation is currently suspended in daemon configuration.",
        }
    mgr = get_acp_manager(agent_dir)
    return await mgr.execute_task_async(cwd=cwd, prompt=prompt, agent_profile=agent_profile)


async def acp_task_status_fn(task_id: str = "", agent_dir: str = "") -> dict[str, Any]:
    """Check status of delegated ACP background tasks."""
    if not get_acp_state(agent_dir).is_running():
        return {
            "status": "error",
            "error": "ACP delegation is currently suspended in daemon configuration.",
        }
    mgr = get_acp_manager(agent_dir)
    return mgr.get_task_status(task_id=task_id)


async def acp_task_result_fn(task_id: str, agent_dir: str = "") -> dict[str, Any]:
    """Fetch output for a completed task_id."""
    if not get_acp_state(agent_dir).is_running():
        return {
            "status": "error",
            "error": "ACP delegation is currently suspended in daemon configuration.",
        }
    mgr = get_acp_manager(agent_dir)
    return mgr.get_task_result(task_id=task_id)


async def acp_task_steer_fn(task_id: str, guidance: str, agent_dir: str = "") -> dict[str, Any]:
    """Steer a running ACP subagent turn."""
    if not get_acp_state(agent_dir).is_running():
        return {
            "status": "error",
            "error": "ACP delegation is currently suspended in daemon configuration.",
        }
    mgr = get_acp_manager(agent_dir)
    task = mgr.get_task_status(task_id)
    if task.get("status") == "not_found":
        return task
    cwd = task.get("cwd", "")
    return await mgr.execute_task_async(cwd=cwd, prompt=f"[STEER]: {guidance}")


async def acp_task_cancel_fn(task_id: str, agent_dir: str = "") -> dict[str, Any]:
    """Cancel an active ACP worker task."""
    if not get_acp_state(agent_dir).is_running():
        return {
            "status": "error",
            "error": "ACP delegation is currently suspended in daemon configuration.",
        }
    mgr = get_acp_manager(agent_dir)
    return mgr.cancel_task(task_id=task_id)


async def acp_list_agents_fn(agent_dir: str = "") -> dict[str, Any]:
    """List active ACP worker processes."""
    if not get_acp_state(agent_dir).is_running():
        return {
            "status": "error",
            "error": "ACP delegation is currently suspended in daemon configuration.",
        }
    mgr = get_acp_manager(agent_dir)
    return mgr.list_agents()


async def acp_inspect_session_fn(session_id: str, agent_dir: str = "") -> dict[str, Any]:
    """Inspect transcript history from an ACP session."""
    if not get_acp_state(agent_dir).is_running():
        return {
            "status": "error",
            "error": "ACP delegation is currently suspended in daemon configuration.",
        }
    return {
        "status": "success",
        "session_id": session_id,
        "history": [],
    }


def get_acp_host_tools() -> list[Any]:
    """Return list of all ACP subagent host tools for RpcClient registration."""
    if host_tool is None:
        return [
            acp_task_async_fn,
            acp_task_status_fn,
            acp_task_result_fn,
            acp_task_steer_fn,
            acp_task_cancel_fn,
            acp_list_agents_fn,
            acp_inspect_session_fn,
        ]

    def _wrap_exec(fn: Any) -> Any:
        def _exec(params: Any, ctx: Any = None) -> Any:
            if isinstance(params, dict):
                return fn(**params)
            return fn()

        return _exec

    return [
        host_tool(
            name="acp_task_async",
            description="Dispatch an asynchronous background subtask to an ACP worker agent. Returns task_id immediately.",
            parameters={
                "type": "object",
                "properties": {
                    "cwd": {
                        "type": "string",
                        "description": "Target workspace directory path",
                    },
                    "prompt": {"type": "string", "description": "Subtask instruction"},
                    "agent_profile": {
                        "type": "string",
                        "description": "Optional agent role",
                    },
                },
                "required": ["cwd", "prompt"],
            },
            execute=_wrap_exec(acp_task_async_fn),
        ),
        host_tool(
            name="acp_task_status",
            description="Check status and telemetry for one or all delegated ACP background tasks.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Optional specific task_id to inspect",
                    }
                },
            },
            execute=_wrap_exec(acp_task_status_fn),
        ),
        host_tool(
            name="acp_task_result",
            description="Fetch final text output and token statistics for a completed ACP task.",
            parameters={
                "type": "object",
                "properties": {"task_id": {"type": "string", "description": "Target task_id"}},
                "required": ["task_id"],
            },
            execute=_wrap_exec(acp_task_result_fn),
        ),
        host_tool(
            name="acp_task_steer",
            description="Inject mid-turn guidance to adjust a running ACP subagent turn.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Target task_id"},
                    "guidance": {
                        "type": "string",
                        "description": "Mid-turn instructions",
                    },
                },
                "required": ["task_id", "guidance"],
            },
            execute=_wrap_exec(acp_task_steer_fn),
        ),
        host_tool(
            name="acp_task_cancel",
            description="Cancel or abort an active ACP worker task.",
            parameters={
                "type": "object",
                "properties": {"task_id": {"type": "string", "description": "Target task_id"}},
                "required": ["task_id"],
            },
            execute=_wrap_exec(acp_task_cancel_fn),
        ),
        host_tool(
            name="acp_list_agents",
            description="List active ACP worker processes, available workspace directories, and agent profiles.",
            parameters={"type": "object", "properties": {}},
            execute=_wrap_exec(acp_list_agents_fn),
        ),
        host_tool(
            name="acp_inspect_session",
            description="Inspect transcript or message history from an ACP worker session.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Target ACP session_id",
                    }
                },
                "required": ["session_id"],
            },
            execute=_wrap_exec(acp_inspect_session_fn),
        ),
    ]


acp_task_async = acp_task_async_fn
acp_task_status = acp_task_status_fn
acp_task_result = acp_task_result_fn
acp_task_steer = acp_task_steer_fn
acp_task_cancel = acp_task_cancel_fn
acp_list_agents = acp_list_agents_fn
acp_inspect_session = acp_inspect_session_fn
