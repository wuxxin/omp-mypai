"""FastAPI Router for ACP state management and worker telemetry."""

from typing import Any

from fastapi import APIRouter, Request

from mypai_tools.acp.manager import get_acp_manager
from mypai_tools.acp.state import get_acp_state

router = APIRouter(prefix="/api/v1/acp", tags=["acp"])


@router.get("/status")
async def get_acp_status(request: Request) -> dict[str, Any]:
    """Get current ACP execution status ('running' vs 'suspended') and worker telemetry."""
    agent_dir = getattr(request.app.state, "agent_dir", "")
    state = get_acp_state(agent_dir)
    manager = get_acp_manager(agent_dir)

    status_data = state.get_status()
    mgr_telemetry = manager.get_task_status()

    running_tasks = [t for t in manager.tasks.values() if t.get("status") == "running"]
    finished_tasks = [
        t for t in manager.tasks.values() if t.get("status") in ("completed", "error", "cancelled")
    ]
    finished_tasks.sort(
        key=lambda x: x.get("completed_at") or x.get("created_at", ""), reverse=True
    )

    status_data.update(
        {
            "total_tasks": len(manager.tasks),
            "active_tasks": len(running_tasks),
            "active_workers": mgr_telemetry.get("active_workers", 0),
            "workers": manager.list_agents().get("workers", []),
            "running_tasks": running_tasks,
            "finished_tasks": finished_tasks[:10],
            "tasks": list(manager.tasks.values()),
        }
    )
    return status_data


@router.get("/tasks/{task_id}")
async def get_acp_task_details(task_id: str, request: Request) -> dict[str, Any]:
    """Fetch details and output for a specific ACP task."""
    from fastapi import HTTPException

    agent_dir = getattr(request.app.state, "agent_dir", "")
    manager = get_acp_manager(agent_dir)
    res = manager.get_task_status(task_id=task_id)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return res


@router.post("/enable")
@router.post("/restart")
async def enable_acp(request: Request) -> dict[str, Any]:
    """Enable / Restart ACP intra-agent delegation execution and worker binary processes."""
    agent_dir = getattr(request.app.state, "agent_dir", "")
    state = get_acp_state(agent_dir)
    manager = get_acp_manager(agent_dir)

    res = state.enable()
    manager.restart_workers()

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast({"event": "acp_state_changed", "state": "running"})

    return res


@router.post("/suspend")
async def suspend_acp(request: Request) -> dict[str, Any]:
    """Suspend ACP intra-agent delegation execution."""
    agent_dir = getattr(request.app.state, "agent_dir", "")
    state = get_acp_state(agent_dir)
    manager = get_acp_manager(agent_dir)

    manager.shutdown_workers()
    res = state.suspend()

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast({"event": "acp_state_changed", "state": "suspended"})

    return res


@router.post("/shutdown")
@router.post("/disable")
async def shutdown_acp(request: Request) -> dict[str, Any]:
    """Shutdown / Disable ACP intra-agent delegation execution and terminate worker binary processes."""
    agent_dir = getattr(request.app.state, "agent_dir", "")
    state = get_acp_state(agent_dir)
    manager = get_acp_manager(agent_dir)

    manager.shutdown_workers()
    res = state.shutdown()

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager:
        await ws_manager.broadcast({"event": "acp_state_changed", "state": "shutdown"})

    return res
