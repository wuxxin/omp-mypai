#!/usr/bin/env python3
"""OMP RPC Session Manager for mypai_daemon."""

import asyncio
import logging
import os
import time
from typing import Any

try:
    from omp_rpc import RpcClient
except ImportError:
    RpcClient = None

logger = logging.getLogger("mypai_daemon.session_manager")


class OMPSessionManager:
    """Manages persistent omp --mode rpc session connected to a fixed session in workspace."""

    def __init__(
        self,
        project_dir: str = "",
        session_name: str | None = None,
    ) -> None:
        self.project_dir = project_dir or os.getenv("MYPAI_PROJECT_DIR", os.getcwd())
        self.session_name = (
            session_name
            or os.getenv("MYPAI_SESSION_NAME")
            or "mypai-main"
        )
        self.rpc_client: Any | None = None
        self._lock = asyncio.Lock()
        self.start_time = time.time()
        self.is_busy = False

    def ensure_connected(self) -> Any | None:
        """Ensure persistent RpcClient is running; re-instantiate if dead or stopped."""
        if RpcClient is None:
            logger.warning("omp_rpc.RpcClient module unavailable.")
            return None

        is_dead = False
        if self.rpc_client is not None:
            proc = getattr(self.rpc_client, "_process", None)
            if proc is None or proc.poll() is not None:
                logger.warning("Persistent RpcClient process has died. Restarting...")
                is_dead = True

        if self.rpc_client is None or is_dead:
            if self.rpc_client is not None:
                try:
                    self.rpc_client.stop()
                except Exception:  # noqa: BLE001
                    pass
                self.rpc_client = None

            try:
                target_cwd = self.project_dir
                kwargs: dict[str, Any] = {
                    "extra_args": [
                        "--auto-approve",
                        "--continue",
                        "--session",
                        self.session_name,
                    ],
                }
                if target_cwd and os.path.isdir(target_cwd):
                    kwargs["cwd"] = target_cwd

                logger.info(
                    "Starting persistent RpcClient (session: '%s', cwd: '%s')...",
                    self.session_name,
                    target_cwd,
                )
                self.rpc_client = RpcClient(**kwargs).start()
                self.rpc_client.install_headless_ui()
                logger.info("Successfully initialized persistent RpcClient.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to start persistent RpcClient: %s", exc)
                self.rpc_client = None

        return self.rpc_client

    async def execute_turn(
        self,
        prompt: str,
        mode: str = "prompt",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a prompt turn through the persistent RPC client.
        
        Supports 4 modes: 'prompt', 'steer', 'followup', 'abort_and_prompt'.
        """
        async with self._lock:
            self.is_busy = True
            client = self.ensure_connected()
            clean_mode = str(mode or "prompt").lower()

            start_time = time.time()
            res_output = ""
            return_code = 0
            error_msg = ""

            try:
                if client is None:
                    raise RuntimeError("RPC Client offline and reconnect failed.")

                logger.info("Sending RPC turn (mode: %s, session: %s): %s", clean_mode, self.session_name, prompt[:60])

                if clean_mode == "steer":
                    if hasattr(client, "steer"):
                        rpc_res = client.steer(prompt)
                    else:
                        rpc_res = client.prompt(f"[STEER INTERRUPT] {prompt}")
                elif clean_mode == "followup":
                    if hasattr(client, "followup"):
                        rpc_res = client.followup(prompt)
                    else:
                        rpc_res = client.prompt(f"[FOLLOWUP] {prompt}")
                elif clean_mode == "abort_and_prompt":
                    if hasattr(client, "abort"):
                        try:
                            client.abort()
                        except Exception:  # noqa: BLE001
                            pass
                    rpc_res = client.prompt(prompt)
                else:  # 'prompt'
                    rpc_res = client.prompt(prompt)

                if isinstance(rpc_res, dict):
                    res_output = (
                        rpc_res.get("response")
                        or rpc_res.get("output")
                        or rpc_res.get("text")
                        or str(rpc_res)
                    )
                elif isinstance(rpc_res, str):
                    res_output = rpc_res
                else:
                    res_output = str(rpc_res or "")

            except Exception as exc:  # noqa: BLE001
                logger.error("RPC Turn execution error: %s", exc)
                return_code = 1
                error_msg = str(exc)
            finally:
                self.is_busy = False

            duration = round(time.time() - start_time, 3)
            return {
                "status": "success" if return_code == 0 else "error",
                "mode": clean_mode,
                "session_name": self.session_name,
                "return_code": return_code,
                "output": res_output,
                "error": error_msg,
                "duration_sec": duration,
            }

    def get_status(self, queue_depth: int = 0) -> dict[str, Any]:
        """Get current session status telemetry."""
        proc = getattr(self.rpc_client, "_process", None) if self.rpc_client else None
        pid = proc.pid if proc and proc.poll() is None else None
        is_connected = pid is not None

        return {
            "status": "connected" if is_connected else "disconnected",
            "pid": pid,
            "session_name": self.session_name,
            "project_dir": self.project_dir,
            "is_busy": self.is_busy,
            "queue_depth": queue_depth,
            "uptime_sec": round(time.time() - self.start_time, 1),
        }
