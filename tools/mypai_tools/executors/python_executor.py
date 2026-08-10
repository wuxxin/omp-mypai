#!/usr/bin/env python3
"""Python Job Executor supporting in-process lambda expressions and async functions using inlined attributes."""

import asyncio
import json
import logging
from typing import Any, Dict

from mypai_tools.db import substitute_env_vars

try:
    from omp_rpc import RpcClient
except ImportError:
    RpcClient = None

logger = logging.getLogger("mypai_heartbeat.python_executor")


async def execute_python_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Python lambda expression or code block in-process using inlined attributes.

    Inlined Attributes:
    - action: Python lambda expression (e.g. 'lambda args, kwargs: {"status": "ok", "count": len(args)}') or code block
    - args: positional args list passed to lambda/code
    - kwargs: keyword args dictionary passed to lambda/code
    - output_prompt: optional output header template supporting #[_RESULT], #[_STDOUT], #[_RETURNCODE] placeholders
    - output_action: 'ignore' (default), 'prompt', 'steer', 'followup', 'abort_and_prompt'
    """
    name = job.get("name", "Unnamed Python Job")
    code = job.get("action") or job.get("code") or job.get("output_prompt") or ""

    if not code:
        raise ValueError("No Python code specified in 'action' or 'code' attributes.")

    args_val = job.get("args") or []
    if isinstance(args_val, str) and args_val.strip().startswith(("[", "{")):
        try:
            args_val = json.loads(args_val)
        except Exception:
            pass

    kwargs_val = job.get("kwargs") or {}
    if isinstance(kwargs_val, str) and kwargs_val.strip().startswith("{"):
        try:
            kwargs_val = json.loads(kwargs_val)
        except Exception:
            pass

    output_action = (job.get("output_action") or "ignore").lower()

    logger.info("Executing Python job '%s'...", name)

    local_namespace: Dict[str, Any] = {}
    global_namespace: Dict[str, Any] = {
        "asyncio": asyncio,
        "job": job,
        "args": args_val,
        "kwargs": kwargs_val,
    }

    try:
        clean_code = code.strip()
        if clean_code.startswith("lambda"):
            fn = eval(clean_code, global_namespace, local_namespace)
            try:
                res = fn(args_val, kwargs_val)
            except TypeError:
                try:
                    res = fn(args_val)
                except TypeError:
                    res = fn()
        else:
            exec(clean_code, global_namespace, local_namespace)
            res = (
                local_namespace.get("result")
                or global_namespace.get("result")
                or "Execution completed."
            )

        if asyncio.iscoroutine(res):
            res = await res

        res_str = json.dumps(res) if isinstance(res, (dict, list)) else str(res)

        internal_vars = {
            "_RETURNCODE": 0,
            "_STDOUT": res_str,
            "_STDERR": "",
            "_STDCOMBINED": res_str,
            "_RESULT": res_str,
            "_OUTPUT": res_str,
        }

        output_prompt_template = job.get("output_prompt") or ""
        if output_prompt_template:
            if "#[" in output_prompt_template:
                final_output = substitute_env_vars(output_prompt_template, extra_vars=internal_vars)
            else:
                final_output = f"{output_prompt_template}\n{res_str}"
        else:
            final_output = res_str

        # Route output_prompt to OMP via omp_rpc using output_action if output_action != ignore
        if output_action != "ignore" and RpcClient is not None and final_output:
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
                logger.warning("Failed to route python output to OMP via RpcClient: %s", exc)

        return {"status": "success", "result": res, "output": final_output}

    except Exception as exc:
        logger.error("Python execution error for job '%s': %s", name, exc)
        return {"status": "error", "error": str(exc)}
