"""AcpDelegationManager for process pool management, task tracking, auto-restart & crash recovery."""

import asyncio
import logging
import os
import time
import uuid
from typing import Any

from mypai_tools.acp.session import AcpClientSession
from mypai_tools.acp.state import get_acp_state

logger = logging.getLogger("mypai_daemon.acp.manager")


class AcpDelegationManager:
    """Manages worker pool of AcpClientSession instances across target workspace directories."""

    def __init__(self, agent_dir: str = "") -> None:
        self.agent_dir = agent_dir
        self.sessions: dict[str, AcpClientSession] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def get_or_create_session(self, cwd: str) -> AcpClientSession:
        """Get existing running AcpClientSession for cwd or spawn a fresh worker process."""
        abs_cwd = os.path.abspath(os.path.expanduser(cwd))
        session = self.sessions.get(abs_cwd)

        if session and session.is_alive():
            return session

        # Process died or never existed: spawn new worker
        logger.info("Initializing ACP worker session in '%s'...", abs_cwd)
        new_session = AcpClientSession(cwd=abs_cwd)
        try:
            new_session.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ACP worker spawn fallback for '%s': %s", abs_cwd, exc)

        self.sessions[abs_cwd] = new_session
        return new_session

    async def execute_task(
        self,
        cwd: str,
        prompt: str,
        agent_profile: str = "",
        mode: str = "default",
        task_id: str = "",
    ) -> dict[str, Any]:
        """Execute a task turn against an ACP worker process."""
        state = get_acp_state(self.agent_dir)
        if not state.is_running():
            return {
                "status": "error",
                "error": "ACP delegation is currently suspended in daemon configuration.",
            }

        task_id = task_id or f"acp-task-{uuid.uuid4().hex[:8]}"
        start_t = time.time()

        async with self._lock:
            session = self.get_or_create_session(cwd)

        full_prompt = f"Role: {agent_profile}\n\n{prompt}" if agent_profile else prompt

        # Execute turn (in executor pool if blocking)
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None, lambda: session.prompt(full_prompt, mode=mode)
        )

        duration = round(time.time() - start_t, 3)
        task_record = {
            "task_id": task_id,
            "cwd": cwd,
            "prompt": prompt,
            "agent_profile": agent_profile,
            "status": res.get("status", "completed"),
            "output": res.get("output", ""),
            "error": res.get("error", ""),
            "session_id": session.session_id,
            "duration_sec": duration,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_t)),
        }

        self.tasks[task_id] = task_record
        return task_record

    async def execute_task_async(
        self, cwd: str, prompt: str, agent_profile: str = ""
    ) -> dict[str, Any]:
        """Dispatch a background task turn and return task_id immediately."""
        state = get_acp_state(self.agent_dir)
        if not state.is_running():
            return {
                "status": "error",
                "error": "ACP delegation is currently suspended in daemon configuration.",
            }

        task_id = f"acp-task-{uuid.uuid4().hex[:8]}"
        task_record = {
            "task_id": task_id,
            "cwd": cwd,
            "prompt": prompt,
            "agent_profile": agent_profile,
            "status": "running",
            "output": "",
            "error": "",
            "session_id": "",
            "duration_sec": 0.0,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.tasks[task_id] = task_record

        async def _background_run() -> None:
            await self.execute_task(
                cwd=cwd, prompt=prompt, agent_profile=agent_profile, task_id=task_id
            )

        asyncio.create_task(_background_run())
        return {"status": "queued", "task_id": task_id}

    def get_task_status(self, task_id: str = "") -> dict[str, Any]:
        """Check status of a specific task_id or return overview of all tasks."""
        if task_id:
            task = self.tasks.get(task_id)
            if not task:
                return {"status": "not_found", "task_id": task_id}
            return task

        active_workers = sum(1 for s in self.sessions.values() if s.is_alive())
        return {
            "status": "active",
            "total_tasks": len(self.tasks),
            "active_workers": active_workers,
            "tasks": list(self.tasks.values()),
        }

    def get_task_result(self, task_id: str) -> dict[str, Any]:
        """Retrieve output result for a completed task_id."""
        task = self.tasks.get(task_id)
        if not task:
            return {"status": "error", "error": f"Task '{task_id}' not found."}
        return task

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Cancel a running task."""
        task = self.tasks.get(task_id)
        if not task:
            return {"status": "error", "error": f"Task '{task_id}' not found."}

        cwd = task.get("cwd", "")
        session = self.sessions.get(cwd)
        if session:
            session.cancel()

        task["status"] = "cancelled"
        return {"status": "cancelled", "task_id": task_id}

    def list_agents(self) -> dict[str, Any]:
        """List active ACP worker processes, workspace directories, and session IDs."""
        workers = []
        for cwd, sess in self.sessions.items():
            workers.append(
                {
                    "cwd": cwd,
                    "session_id": sess.session_id,
                    "alive": sess.is_alive(),
                    "pid": sess.process.pid if sess.process else None,
                    "uptime_sec": round(time.time() - sess.start_time, 1),
                }
            )
        return {"status": "success", "workers": workers}

    def shutdown(self) -> None:
        """Stop all active worker subprocesses."""
        for sess in self.sessions.values():
            sess.stop()
        self.sessions.clear()


_acp_manager_instances: dict[str, AcpDelegationManager] = {}


def get_acp_manager(agent_dir: str = "") -> AcpDelegationManager:
    """Get or create singleton AcpDelegationManager instance for agent_dir."""
    if agent_dir not in _acp_manager_instances:
        _acp_manager_instances[agent_dir] = AcpDelegationManager(agent_dir=agent_dir)
    return _acp_manager_instances[agent_dir]
