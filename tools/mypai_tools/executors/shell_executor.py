"""Shell Job Executor with inlined attributes, command args & kwargs formatting, and stream routing."""

import asyncio
import json
import logging
import os
import shlex
from typing import Any

from mypai_tools.db import substitute_env_vars

try:
    from omp_rpc import RpcClient
except ImportError:
    RpcClient = None

logger = logging.getLogger("mypai_heartbeat.shell_executor")


def build_full_command(cmd: str, args_val: Any = None, kwargs_val: Any = None) -> str:
    """Combine base command string with positional args (list/str) and flag kwargs (dict)."""
    base_cmd = cmd.strip()

    # Parse args if JSON string
    if isinstance(args_val, str) and args_val.strip().startswith(("[", "{")):
        try:
            args_val = json.loads(args_val)
        except Exception:  # noqa: BLE001, S110
            pass

    # Parse kwargs if JSON string
    if isinstance(kwargs_val, str) and kwargs_val.strip().startswith("{"):
        try:
            kwargs_val = json.loads(kwargs_val)
        except Exception:  # noqa: BLE001, S110
            pass

    parts = [base_cmd]

    # Process positional args
    if isinstance(args_val, list):
        for a in args_val:
            parts.append(shlex.quote(str(a)))
    elif isinstance(args_val, str) and args_val.strip():
        parts.append(args_val.strip())

    # Process flag kwargs
    if isinstance(kwargs_val, dict):
        for k, v in kwargs_val.items():
            prefix = f"--{k}" if len(k) > 1 else f"-{k}"
            if v is True:
                parts.append(prefix)
            elif v is not False and v is not None:
                parts.append(f"{prefix} {shlex.quote(str(v))}")

    return " ".join(parts).strip()


async def execute_shell_job(job: dict[str, Any]) -> dict[str, Any]:
    """Execute shell command using action as base command, positional args list, and flag kwargs.

    Inlined Attributes:
    - action: base CLI binary or script executable string (e.g. 'python3', 'ls', 'echo')
    - args: positional argument list or string
    - kwargs: dictionary of flag parameters
    - result_prompt: optional result context template supporting #[_STDOUT], #[_STDERR], #[_RETURNCODE], #[_OUTPUT]
    - result_error_prompt: optional error result template used on exitlevel != 0
    - result_action: 'ignore' (default), 'prompt', 'steer', 'followup', 'abort_and_prompt'
    """
    name = job.get("name", "Unnamed Shell Job")
    raw_cmd = job.get("action") or ""
    if not raw_cmd:
        raise ValueError("No CLI shell command specified in 'action' attribute.")

    args_val = job.get("args")
    kwargs_val = job.get("kwargs")
    cmd = build_full_command(raw_cmd, args_val, kwargs_val)

    result_action = (job.get("result_action") or "ignore").lower()

    logger.info("Executing shell command '%s' for job '%s'...", cmd, name)

    env = os.environ.copy()
    proc = await asyncio.create_subprocess_shell(
        cmd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    exit_code = proc.returncode

    stdout_str = stdout.decode("utf-8", errors="replace").strip()
    stderr_str = stderr.decode("utf-8", errors="replace").strip()
    combined_str = f"STDOUT:\n{stdout_str}\n\nSTDERR:\n{stderr_str}".strip()

    internal_vars = {
        "_RETURNCODE": exit_code,
        "_STDOUT": stdout_str,
        "_STDERR": stderr_str,
        "_RESULT": stdout_str,
        "_OUTPUT": combined_str,
    }

    if exit_code != 0:
        result_prompt_template = (
            job.get("result_error_prompt") or job.get("result_prompt") or ""
        )
    else:
        result_prompt_template = job.get("result_prompt") or ""

    if result_prompt_template:
        if "#[" in result_prompt_template:
            final_output = substitute_env_vars(result_prompt_template, extra_vars=internal_vars)
        else:
            out_body = stdout_str if exit_code == 0 else (stderr_str or stdout_str)
            final_output = f"{result_prompt_template}\n{out_body}"
    else:
        final_output = stdout_str

    logger.info("Shell job '%s' exited with code %d", name, exit_code)

    # Route result_prompt to OMP via omp_rpc using result_action if result_action != ignore
    if result_action != "ignore" and RpcClient is not None and final_output:
        try:
            with RpcClient() as client:
                client.install_headless_ui()
                if result_action in ("prompt", "prompt_and_wait"):
                    client.prompt(final_output)
                elif result_action == "steer":
                    client.steer(final_output)
                elif result_action in ("followup", "follow_up"):
                    client.follow_up(final_output)
                elif result_action == "abort_and_prompt":
                    client.abort_and_prompt(final_output)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to route shell output to OMP via RpcClient: %s", exc)

    return {
        "status": "success" if exit_code == 0 else "error",
        "exit_code": exit_code,
        "full_command": cmd,
        "stdout": stdout_str,
        "stderr": stderr_str,
        "output": final_output,
    }
