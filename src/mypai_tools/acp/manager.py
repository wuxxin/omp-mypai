"""AcpDelegationManager for async process pool management, task tracking, auto-restart & crash recovery."""

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
    """Manages worker pool of AcpClientSession instances across target workspace directories.

    ACP workers never inherit the daemon's profile; they execute against the main/default
    Oh-My-Pi profile by default so that they control external Oh-My-Pi worker instances.
    """

    def __init__(self, agent_dir: str = "", profile: str = "") -> None:
        self.agent_dir = agent_dir
        self.profile = profile
        self.sessions: dict[str, AcpClientSession] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.daemon_queue: Any = None
        self.ws_manager: Any = None

    def set_daemon_queue(self, queue: Any) -> None:
        """Attach daemon TurnQueue for automatic completion callbacks."""
        self.daemon_queue = queue

    def set_ws_manager(self, ws_mgr: Any) -> None:
        """Attach daemon WebSocket manager for live task updates."""
        self.ws_manager = ws_mgr

    def get_or_create_session(self, cwd: str) -> AcpClientSession:
        """Get existing running AcpClientSession for cwd or spawn a fresh worker process."""
        abs_cwd = os.path.abspath(os.path.expanduser(cwd))
        session = self.sessions.get(abs_cwd)

        if session and session.is_alive():
            return session

        logger.info(
            "Initializing ACP worker session in '%s' (profile: %s)...",
            abs_cwd,
            self.profile or "default (main)",
        )
        new_session = AcpClientSession(cwd=abs_cwd, profile=self.profile)
        try:
            new_session.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ACP worker spawn fallback for '%s': %s", abs_cwd, exc)

        self.sessions[abs_cwd] = new_session
        return new_session

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
        task_record: dict[str, Any] = {
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
            "completed_at": None,
        }
        self.tasks[task_id] = task_record

        if self.ws_manager:
            try:
                await self.ws_manager.broadcast({"event": "acp_task_started", "task": task_record})
            except Exception as ws_exc:  # noqa: BLE001
                logger.debug("Error broadcasting acp_task_started: %s", ws_exc)

        async def _background_run() -> None:
            start_t = time.time()
            try:
                async with self._lock:
                    session = self.get_or_create_session(cwd)

                full_prompt = f"Role: {agent_profile}\n\n{prompt}" if agent_profile else prompt
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(None, lambda: session.prompt(full_prompt))

                raw_status = res.get("status", "completed")
                task_status = "completed" if raw_status in ("success", "completed") else "error"
                duration = round(time.time() - start_t, 3)
                task_record.update(
                    {
                        "status": task_status,
                        "output": res.get("output", ""),
                        "error": res.get("error", ""),
                        "session_id": session.session_id,
                        "duration_sec": duration,
                        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                duration = round(time.time() - start_t, 3)
                task_record.update(
                    {
                        "status": "error",
                        "error": str(exc),
                        "duration_sec": duration,
                        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                )

            if self.ws_manager:
                try:
                    await self.ws_manager.broadcast(
                        {"event": "acp_task_completed", "task": task_record}
                    )
                except Exception as ws_exc:  # noqa: BLE001
                    logger.debug("Error broadcasting acp_task_completed: %s", ws_exc)

            if self.daemon_queue:
                status_title = "Completed" if task_record["status"] == "completed" else "Failed"
                cb_prompt = (
                    f"[ACP Subagent Task {status_title}]\n"
                    f"Task ID: {task_id}\n"
                    f"Workspace: {cwd}\n"
                    f"Role: {agent_profile or 'default'}\n"
                    f"Duration: {task_record.get('duration_sec', 0.0)}s\n\n"
                    f"Result Output:\n{task_record.get('output', '')}"
                )
                if task_record["status"] == "error":
                    cb_prompt += f"\nError: {task_record.get('error', '')}"

                try:
                    await self.daemon_queue.enqueue(
                        prompt=cb_prompt,
                        mode="prompt",
                        source="acp_callback",
                        priority=2,
                        context={"task_id": task_id, "source": "acp_callback", "cwd": cwd},
                    )
                except Exception as q_exc:  # noqa: BLE001
                    logger.warning("Failed to enqueue ACP callback to TurnQueue: %s", q_exc)

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

    def shutdown_workers(self) -> None:
        """Stop all active worker subprocesses and terminate binary instances."""
        logger.info("Shutting down all active ACP worker subprocesses...")
        for sess in list(self.sessions.values()):
            try:
                sess.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error stopping ACP session process: %s", exc)
        self.sessions.clear()

    def restart_workers(self) -> None:
        """Restart worker subprocess pool for workspace directory."""
        logger.info("Restarting ACP worker process pool...")
        self.shutdown_workers()
        if self.agent_dir and os.path.isdir(self.agent_dir):
            self.get_or_create_session(self.agent_dir)

    def shutdown(self) -> None:
        """Stop all active worker subprocesses."""
        self.shutdown_workers()


_acp_manager_instances: dict[str, AcpDelegationManager] = {}


def get_acp_manager(agent_dir: str = "") -> AcpDelegationManager:
    """Get or create singleton AcpDelegationManager instance for agent_dir."""
    if agent_dir not in _acp_manager_instances:
        _acp_manager_instances[agent_dir] = AcpDelegationManager(agent_dir=agent_dir)
    return _acp_manager_instances[agent_dir]
