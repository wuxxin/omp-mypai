"""ACP Client Session interface wrapping stdio JSON-RPC communication with omp --mode acp subprocesses."""

import json
import logging
import os
import subprocess
import time
from typing import Any

logger = logging.getLogger("mypai_daemon.acp.session")


class AcpClientSession:
    """Manages an active omp --mode acp worker process over stdio JSON-RPC streams."""

    def __init__(self, cwd: str, extra_args: list[str] | None = None) -> None:
        self.cwd = os.path.abspath(os.path.expanduser(cwd))
        self.extra_args = extra_args or []
        self.process: subprocess.Popen[bytes] | None = None
        self.session_id: str = ""
        self.start_time: float = time.time()
        self._request_counter = 0

    def start(self) -> "AcpClientSession":
        """Spawn the underlying `omp --mode acp` subprocess."""
        cmd = ["omp", "--mode", "acp"] + self.extra_args
        logger.info("Spawning ACP worker process in '%s': %s", self.cwd, cmd)

        self.process = subprocess.Popen(
            cmd,
            cwd=self.cwd if os.path.isdir(self.cwd) else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.start_time = time.time()
        self._initialize_handshake()
        return self

    def _next_id(self) -> int:
        self._request_counter += 1
        return self._request_counter

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request to the ACP child process and read response line."""
        if not self.process or self.process.poll() is not None:
            raise RuntimeError(f"ACP worker process in '{self.cwd}' is not running.")

        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        msg = (json.dumps(payload) + "\n").encode("utf-8")

        assert self.process.stdin is not None
        assert self.process.stdout is not None

        self.process.stdin.write(msg)
        self.process.stdin.flush()

        # Read lines until we find the matching response for req_id
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(f"ACP worker stdio stream closed for method '{method}'.")
            try:
                resp = json.loads(line.decode("utf-8").strip())
                if isinstance(resp, dict) and resp.get("id") == req_id:
                    if "error" in resp:
                        raise RuntimeError(f"ACP JSON-RPC Error: {resp['error']}")
                    return resp.get("result", {})
            except json.JSONDecodeError:
                continue

    def _initialize_handshake(self) -> None:
        """Perform initial ACP protocol handshake (initialize & session/new)."""
        try:
            init_res = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "mypai_daemon_acp_client", "version": "1.0.0"},
                    "capabilities": {},
                },
            )
            logger.debug("ACP initialize handshake success: %s", init_res)

            new_sess_res = self._send_request("session/new", {"cwd": self.cwd})
            self.session_id = new_sess_res.get("sessionId") or new_sess_res.get("session_id") or "acp-session"
            logger.info("Created ACP session '%s' in '%s'.", self.session_id, self.cwd)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ACP handshake fallback (sub-process starting in basic mode): %s", exc)

    def is_alive(self) -> bool:
        """Check if child process is running."""
        return self.process is not None and self.process.poll() is None

    def prompt(self, message: str, mode: str = "default", timeout: float = 120.0) -> dict[str, Any]:
        """Submit a prompt turn to the ACP worker and await completion."""
        start_t = time.time()
        try:
            res = self._send_request(
                "session/prompt",
                {
                    "sessionId": self.session_id,
                    "prompt": message,
                    "mode": mode,
                },
            )
            duration = round(time.time() - start_t, 3)
            output_text = res.get("text") or res.get("output") or str(res)
            return {
                "status": "success",
                "output": output_text,
                "session_id": self.session_id,
                "duration_sec": duration,
                "raw": res,
            }
        except Exception as exc:  # noqa: BLE001
            duration = round(time.time() - start_t, 3)
            return {
                "status": "error",
                "error": str(exc),
                "session_id": self.session_id,
                "duration_sec": duration,
            }

    def cancel(self) -> dict[str, Any]:
        """Cancel active prompt turn in child process."""
        try:
            res = self._send_request("session/cancel", {"sessionId": self.session_id})
            return {"status": "cancelled", "result": res}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    def stop(self) -> None:
        """Terminate the child subprocess gracefully."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:  # noqa: BLE001
                try:
                    self.process.kill()
                except Exception:  # noqa: BLE001, S110
                    pass
            finally:
                self.process = None
