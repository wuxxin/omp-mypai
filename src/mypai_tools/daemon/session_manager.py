"""OMP RPC Session Manager for mypai_daemon."""

import asyncio
import logging
import os
import time
from typing import Any

from mypai_tools.persistence import (
    get_db_session,
    get_setting,
    resolve_agent_dir,
    set_setting,
)

try:
    from omp_rpc import RpcClient
except ImportError:
    RpcClient = None

logger = logging.getLogger("mypai_daemon.session_manager")


def format_human_uptime(seconds: float) -> str:
    """Format duration in seconds into human readable duration string (e.g. '12m 34s' or '1h 05m')."""
    total = int(max(0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


class OMPSessionManager:
    """Manages persistent omp --mode rpc session connected to a workspace directory."""

    def __init__(self, agent_dir: str = "", session_name: str | None = None) -> None:
        self.agent_dir = resolve_agent_dir(agent_dir)
        self.session_name = "mypai_daemon - running"
        self.session_uuid = ""
        self.rpc_client: Any | None = None
        self._lock = asyncio.Lock()
        self.start_time = time.time()
        self.is_busy = False

    def _setup_event_listeners(self, client: Any) -> None:
        """Attach RPC streaming event listeners to forward live events to WebSocket clients."""
        try:
            from mypai_tools.daemon.api.ws import ws_manager

            loop = asyncio.get_event_loop()

            def broadcast_event(event_type: str, data: dict[str, Any]) -> None:
                if loop.is_running():
                    payload = {"event": event_type, **data}
                    asyncio.run_coroutine_threadsafe(
                        ws_manager.broadcast(payload), loop
                    )

            def _extract_text(evt: Any) -> str:
                if hasattr(evt, "text") and isinstance(evt.text, str) and evt.text:
                    return evt.text
                msg_evt = getattr(evt, "assistant_message_event", None)
                if msg_evt is not None:
                    if isinstance(msg_evt, dict):
                        return msg_evt.get("delta") or msg_evt.get("content") or ""
                    return (
                        getattr(msg_evt, "delta", None)
                        or getattr(msg_evt, "content", None)
                        or ""
                    )
                return str(evt) if isinstance(evt, str) else ""

            if hasattr(client, "on_message_update"):

                def _on_update(evt: Any) -> None:
                    text = _extract_text(evt)
                    if text:
                        broadcast_event("message_update", {"text": text})

                client.on_message_update(_on_update)
            if hasattr(client, "on_turn_start"):
                client.on_turn_start(
                    lambda evt: broadcast_event(
                        "rpc_turn_start",
                        {"turn": getattr(evt, "turn_id", "")},
                    )
                )
            if hasattr(client, "on_turn_end"):
                client.on_turn_end(
                    lambda evt: broadcast_event(
                        "rpc_turn_end",
                        {"turn": getattr(evt, "turn_id", "")},
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to set up event listeners on RpcClient: %s", exc)

    def ensure_connected(self) -> Any | None:
        """Ensure persistent RpcClient is running; re-instantiate or reattach using DB session_uuid."""
        if RpcClient is None:
            logger.warning("omp_rpc.RpcClient module unavailable.")
            return None

        is_dead = False
        if self.rpc_client is not None:
            proc = getattr(self.rpc_client, "_process", None)
            if proc is None or proc.poll() is not None:
                logger.warning(
                    "Persistent RpcClient process has died. Re-connecting..."
                )
                is_dead = True

        if self.rpc_client is None or is_dead:
            if self.rpc_client is not None:
                try:
                    self.rpc_client.stop()
                except Exception:  # noqa: BLE001, S110
                    pass
                self.rpc_client = None

            db = get_db_session(self.agent_dir)
            try:
                saved_uuid = get_setting(db, "session_uuid")
                client = None

                # Attempt 1: Reattach to existing session_uuid if saved in DB
                if saved_uuid:
                    try:
                        logger.info(
                            "Attempting to reattach to saved session UUID '%s' in '%s'...",
                            saved_uuid,
                            self.agent_dir,
                        )
                        kwargs: dict[str, Any] = {
                            "extra_args": ["--auto-approve", "--resume", saved_uuid],
                        }
                        if os.path.isdir(self.agent_dir):
                            kwargs["cwd"] = self.agent_dir
                        client = RpcClient(**kwargs).start()
                        if hasattr(client, "set_session_name"):
                            client.set_session_name("mypai_daemon - running")
                        self.session_uuid = saved_uuid
                        logger.info(
                            "Successfully reattached to session UUID '%s'.", saved_uuid
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Failed to reattach to session UUID '%s': %s. Creating new session...",
                            saved_uuid,
                            exc,
                        )
                        client = None

                # Attempt 2: Create new session if no saved_uuid or reattach failed
                if client is None:
                    kwargs = {
                        "extra_args": ["--auto-approve"],
                    }
                    if os.path.isdir(self.agent_dir):
                        kwargs["cwd"] = self.agent_dir

                    logger.info(
                        "Spawning new persistent RpcClient in '%s'...", self.agent_dir
                    )
                    client = RpcClient(**kwargs).start()
                    if hasattr(client, "new_session"):
                        try:
                            client.new_session()
                        except Exception:  # noqa: BLE001, S110
                            pass

                    new_uuid = ""
                    if hasattr(client, "get_state"):
                        try:
                            st = client.get_state()
                            new_uuid = getattr(st, "session_id", "") or ""
                        except Exception:  # noqa: BLE001, S110
                            pass

                    if not new_uuid:
                        import uuid

                        new_uuid = str(uuid.uuid4())

                    set_setting(db, "session_uuid", new_uuid)
                    if hasattr(client, "set_session_name"):
                        client.set_session_name("mypai_daemon - running")

                    self.session_uuid = new_uuid
                    logger.info("Created new persistent session UUID '%s'.", new_uuid)

                if hasattr(client, "install_headless_ui"):
                    client.install_headless_ui()

                self._setup_event_listeners(client)

                if hasattr(client, "set_custom_tools"):
                    try:
                        from mypai_tools.acp.tools import get_acp_host_tools

                        client.set_custom_tools(get_acp_host_tools())
                        logger.info(
                            "Registered 8 ACP host tools into persistent RpcClient."
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "Failed to register ACP host tools into RpcClient: %s", exc
                        )

                self.rpc_client = client
                self.session_name = "mypai_daemon - running"

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to initialize persistent RpcClient in '%s': %s",
                    self.agent_dir,
                    exc,
                )
                self.rpc_client = None
            finally:
                db.close()

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
                    raise RuntimeError(
                        f"RPC Client offline. Session '{self.session_name}' failed in '{self.agent_dir}'."
                    )

                logger.info(
                    "Sending RPC turn (mode: %s, session: %s): %s",
                    clean_mode,
                    self.session_uuid,
                    prompt[:60],
                )

                if clean_mode == "steer":
                    if hasattr(client, "steer"):
                        rpc_res = client.steer(prompt)
                    else:
                        rpc_res = client.prompt(f"[STEER INTERRUPT] {prompt}")
                    if hasattr(client, "wait_for_idle"):
                        client.wait_for_idle()
                elif clean_mode == "followup":
                    if hasattr(client, "followup"):
                        rpc_res = client.followup(prompt)
                    else:
                        rpc_res = client.prompt(f"[FOLLOWUP] {prompt}")
                    if hasattr(client, "wait_for_idle"):
                        client.wait_for_idle()
                elif clean_mode == "abort_and_prompt":
                    if hasattr(client, "abort"):
                        try:
                            client.abort()
                        except Exception:  # noqa: BLE001, S110
                            pass
                    if hasattr(client, "prompt_and_wait"):
                        rpc_res = client.prompt_and_wait(prompt)
                    else:
                        rpc_res = client.prompt(prompt)
                else:  # 'prompt'
                    if hasattr(client, "prompt_and_wait"):
                        rpc_res = client.prompt_and_wait(prompt)
                    else:
                        rpc_res = client.prompt(prompt)

                if hasattr(rpc_res, "assistant_text"):
                    res_output = rpc_res.assistant_text or ""
                elif isinstance(rpc_res, dict):
                    res_output = (
                        rpc_res.get("response")
                        or rpc_res.get("output")
                        or rpc_res.get("assistant_text")
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
                "session_uuid": self.session_uuid,
                "return_code": return_code,
                "output": res_output,
                "error": error_msg,
                "duration_sec": duration,
            }

    def get_session_stats(self) -> dict[str, Any]:
        """Fetch session statistics from omp_rpc client."""
        client = self.ensure_connected()
        if client and hasattr(client, "get_session_stats"):
            try:
                stats = client.get_session_stats()
                if hasattr(stats, "__dataclass_fields__"):
                    tokens_dict = {}
                    if hasattr(stats.tokens, "__dataclass_fields__"):
                        tokens_dict = {
                            "input": getattr(stats.tokens, "input", 0),
                            "output": getattr(stats.tokens, "output", 0),
                            "total": getattr(stats.tokens, "total", 0),
                        }
                    return {
                        "session_id": getattr(stats, "session_id", self.session_uuid),
                        "session_file": getattr(stats, "session_file", None),
                        "user_messages": getattr(stats, "user_messages", 0),
                        "assistant_messages": getattr(stats, "assistant_messages", 0),
                        "tool_calls": getattr(stats, "tool_calls", 0),
                        "tool_results": getattr(stats, "tool_results", 0),
                        "total_messages": getattr(stats, "total_messages", 0),
                        "tokens": tokens_dict,
                        "cost": float(getattr(stats, "cost", 0.0)),
                    }
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error fetching session stats from RpcClient: %s", exc)

        return {
            "session_id": self.session_uuid,
            "session_file": None,
            "user_messages": 0,
            "assistant_messages": 0,
            "tool_calls": 0,
            "tool_results": 0,
            "total_messages": 0,
            "tokens": {"input": 0, "output": 0, "total": 0},
            "cost": 0.0,
        }

    def get_status(self, queue_depth: int = 0) -> dict[str, Any]:
        """Get current session status telemetry."""
        proc = getattr(self.rpc_client, "_process", None) if self.rpc_client else None
        pid = proc.pid if proc and proc.poll() is None else None
        is_connected = pid is not None

        uptime = round(time.time() - self.start_time, 1)
        return {
            "status": "connected" if is_connected else "disconnected",
            "version": "1.0.0",
            "pid": pid,
            "session_name": self.session_name,
            "session_id": self.session_uuid,
            "agent_dir": self.agent_dir,
            "is_busy": self.is_busy,
            "queue_depth": queue_depth,
            "uptime_sec": uptime,
            "human_uptime": format_human_uptime(uptime),
        }
