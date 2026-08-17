"""Shell Job Executor with custom env injection, timeout opts, and error/disable lambdas."""

import asyncio
import json
import logging
import os
import shlex
import time
from typing import Any

from mypai_tools.executors.omp_rpc_executor import dispatch_result_to_omp
from mypai_tools.tools import (
    build_internal_vars,
    evaluate_and_dispatch_result_prompt,
    substitute_vars,
)

logger = logging.getLogger("mypai_daemon.executors.shell")


def build_full_command(cmd: str, args_val: Any = None) -> str:
    """Combine base command string with positional args (list/str)."""
    base_cmd = cmd.strip()

    if isinstance(args_val, str) and args_val.strip().startswith(("[", "{")):
        try:
            args_val = json.loads(args_val)
        except Exception:  # noqa: BLE001
            pass

    parts = [base_cmd]

    if isinstance(args_val, list):
        for a in args_val:
            parts.append(shlex.quote(str(a)))
    elif isinstance(args_val, str) and args_val.strip():
        parts.append(args_val.strip())

    return " ".join(parts).strip()


async def execute_shell_job(
    job: dict[str, Any],
    daemon_queue: Any | None = None,
    session_mgr: Any | None = None,
) -> dict[str, Any]:
    """Execute shell command with env injection, timeout protection, and telemetry."""
    start_time = time.time()
    job = substitute_vars(job)
    name = job.get("name", "Unnamed Shell Job")
    raw_cmd = job.get("action") or ""
    if not raw_cmd:
        raise ValueError("No CLI shell command specified in 'action' attribute.")

    args_val = job.get("args")
    cmd = build_full_command(raw_cmd, args_val)

    opts = job.get("opts") if isinstance(job.get("opts"), dict) else {}
    timeout_sec = float(opts.get("timeout_sec") or 120.0)

    # Build environment by injecting opts.env
    env = os.environ.copy()
    if isinstance(opts.get("env"), dict):
        for k, v in opts["env"].items():
            env[str(k)] = str(v)

    logger.info(
        "Executing shell command '%s' for job '%s' (timeout: %.1fs)...", cmd, name, timeout_sec
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            exit_code = proc.returncode or 0
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            stdout = b""
            stderr = f"Command timed out after {timeout_sec}s".encode()
            exit_code = 124

    except Exception as exc:  # noqa: BLE001
        stdout = b""
        stderr = str(exc).encode("utf-8")
        exit_code = 1

    duration = round(time.time() - start_time, 3)
    stdout_str = stdout.decode("utf-8", errors="replace").strip()
    stderr_str = stderr.decode("utf-8", errors="replace").strip()

    # Optional error_on lambda evaluation
    is_success = exit_code == 0
    if opts.get("error_on"):
        try:
            error_fn = eval(opts["error_on"])
            eval_res = error_fn(args_val, {"_ERROR_LEVEL": exit_code, "_RETURN_CODE": exit_code})
            if eval_res is True:
                is_success = False
            elif eval_res is False:
                is_success = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error evaluating error_on lambda: %s", exc)

    internal_vars = build_internal_vars(
        job,
        return_code=exit_code,
        output=stdout_str,
        error=stderr_str,
        obj={"exit_code": exit_code, "command": cmd},
        http_code=0,
        duration=duration,
    )

    default_out = stdout_str if is_success else (stderr_str or stdout_str)
    final_output = evaluate_and_dispatch_result_prompt(
        job,
        internal_vars,
        is_success=is_success,
        default_output=default_out,
        daemon_queue=daemon_queue,
        session_mgr=session_mgr,
        dispatch_fn=dispatch_result_to_omp,
    )

    logger.info("Shell job '%s' exited with code %d (success: %s)", name, exit_code, is_success)

    return {
        "status": "success" if is_success else "error",
        "kind": "shell",
        "action": cmd,
        "return_code": exit_code,
        "output": final_output,
        "error": stderr_str,
        "object": {"exit_code": exit_code, "command": cmd},
        "duration_sec": duration,
    }
