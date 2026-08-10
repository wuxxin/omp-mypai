#!/usr/bin/env python3
"""Shell Job Executor with inlined attributes, command args & kwargs formatting, and stream routing."""

import asyncio
import json
import logging
import os
import shlex
from typing import Any, Dict

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
        except Exception:
            pass

    # Parse kwargs if JSON string
    if isinstance(kwargs_val, str) and kwargs_val.strip().startswith("{"):
        try:
            kwargs_val = json.loads(kwargs_val)
        except Exception:
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


async def execute_shell_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Execute shell command using action as base command, positional args list, and flag kwargs.

    Inlined Attributes:
    - action: base CLI binary or script executable string (e.g. 'python3', 'ls', 'echo')
    - args: positional argument list or string
    - kwargs: dictionary of flag parameters
    - output_prompt: optional output header template supporting #[_STDOUT], #[_STDERR], #[_RETURNCODE], #[_STDCOMBINED]
    - output_type: 'stdout' (default), 'stderr', 'combined'
    - output_action: 'ignore' (default), 'prompt', 'steer', 'followup', 'abort_and_prompt'
    """
    name = job.get("name", "Unnamed Shell Job")
    raw_cmd = job.get("action") or job.get("command") or job.get("output_prompt") or ""
    if not raw_cmd:
        raise ValueError("No CLI shell command specified in 'action' or 'command' attributes.")

    args_val = job.get("args")
    kwargs_val = job.get("kwargs")
    cmd = build_full_command(raw_cmd, args_val, kwargs_val)

    output_type = (job.get("output_type") or "stdout").lower()
    output_action = (job.get("output_action") or "ignore").lower()

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

    if output_type == "stderr":
        selected_output = stderr_str
    elif output_type == "combined":
        selected_output = combined_str
    else:
        selected_output = stdout_str

    internal_vars = {
        "_RETURNCODE": exit_code,
        "_STDOUT": stdout_str,
        "_STDERR": stderr_str,
        "_STDCOMBINED": combined_str,
        "_RESULT": selected_output,
        "_OUTPUT": selected_output,
    }

    output_prompt_template = job.get("output_prompt") or ""
    if output_prompt_template:
        if "#[" in output_prompt_template:
            final_output = substitute_env_vars(output_prompt_template, extra_vars=internal_vars)
        else:
            final_output = f"{output_prompt_template}\n{selected_output}"
    else:
        final_output = selected_output

    logger.info("Shell job '%s' exited with code %d", name, exit_code)

    # Route output to OMP via omp_rpc if requested
    if output_action != "ignore" and RpcClient is not None and selected_output:
        try:
            with RpcClient() as client:
                client.install_headless_ui()
                if output_action in ("prompt", "prompt_and_wait"):
                    client.prompt(final_output)
                elif output_action == "steer":
                    client.steer(final_output)
                elif output_action in ("followup", "follow_up"):
                    client.follow_up(final_output)
                elif output_action == "abort_and_prompt":
                    client.abort_and_prompt(final_output)
        except Exception as exc:
            logger.warning("Failed to route shell output to OMP via RpcClient: %s", exc)

    return {
        "status": "success" if exit_code == 0 else "error",
        "exit_code": exit_code,
        "full_command": cmd,
        "stdout": stdout_str,
        "stderr": stderr_str,
        "output": final_output,
    }
