"""Python Job Executor supporting in-process lambda expressions and async functions using inlined attributes."""

import asyncio
import json
import logging
from typing import Any

from mypai_tools.db import substitute_env_vars

try:
    from omp_rpc import RpcClient
except ImportError:
    RpcClient = None

logger = logging.getLogger("mypai_heartbeat.python_executor")


async def execute_python_job(job: dict[str, Any]) -> dict[str, Any]:
    """Execute Python lambda expression or code block in-process using inlined attributes.

    Inlined Attributes:
    - action: Python lambda expression (e.g. 'lambda args, kwargs: {"status": "ok", "count": len(args)}') or code block
    - args: positional args list passed to lambda/code
    - kwargs: keyword args dictionary passed to lambda/code
    - result_prompt: optional result header template supporting #[_RESULT], #[_STDOUT], #[_RETURNCODE] placeholders
    - result_error_prompt: optional error result template used on exitlevel != 0
    - result_action: 'ignore' (default), 'prompt', 'steer', 'followup', 'abort_and_prompt'
    """
    name = job.get("name", "Unnamed Python Job")
    code = job.get("action") or ""
    if not code:
        raise ValueError("No Python code specified in 'action' attribute.")

    args_val = job.get("args") or []
    if isinstance(args_val, str) and args_val.strip().startswith(("[", "{")):
        try:
            args_val = json.loads(args_val)
        except Exception:  # noqa: BLE001, S110
            pass

    kwargs_val = job.get("kwargs") or {}
    if isinstance(kwargs_val, str) and kwargs_val.strip().startswith("{"):
        try:
            kwargs_val = json.loads(kwargs_val)
        except Exception:  # noqa: BLE001, S110
            pass

    result_action = (job.get("result_action") or "ignore").lower()

    logger.info("Executing Python job '%s'...", name)

    local_namespace: dict[str, Any] = {}
    global_namespace: dict[str, Any] = {
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
            exec(clean_code, global_namespace, local_namespace)  # noqa: S102
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
            "_RESULT": res_str,
            "_OUTPUT": res_str,
        }

        result_prompt_template = job.get("result_prompt") or ""
        if result_prompt_template:
            if "#[" in result_prompt_template:
                final_output = substitute_env_vars(result_prompt_template, extra_vars=internal_vars)
            else:
                final_output = f"{result_prompt_template}\n{res_str}"
        else:
            final_output = res_str

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
                logger.warning("Failed to route python output to OMP via RpcClient: %s", exc)

        return {"status": "success", "result": res, "output": final_output}

    except Exception as exc:  # noqa: BLE001
        logger.error("Python execution error for job '%s': %s", name, exc)
        err_str = str(exc)
        internal_vars = {
            "_RETURNCODE": 1,
            "_STDOUT": "",
            "_STDERR": err_str,
            "_RESULT": err_str,
            "_OUTPUT": err_str,
        }

        result_prompt_template = (
            job.get("result_error_prompt") or job.get("result_prompt") or ""
        )
        if result_prompt_template:
            if "#[" in result_prompt_template:
                final_output = substitute_env_vars(result_prompt_template, extra_vars=internal_vars)
            else:
                final_output = f"{result_prompt_template}\n{err_str}"
        else:
            final_output = err_str

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
            except Exception as rpc_exc:  # noqa: BLE001
                logger.warning("Failed to route python error output to OMP via RpcClient: %s", rpc_exc)

        return {"status": "error", "error": err_str, "output": final_output}
