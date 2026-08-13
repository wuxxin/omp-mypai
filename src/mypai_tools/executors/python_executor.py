"""Python Job Executor supporting in-process lambda expressions and async functions using inlined attributes."""

import asyncio
import json
import logging
import time
from typing import Any

from mypai_tools.executors.omp_rpc_executor import dispatch_result_to_omp
from mypai_tools.tools import substitute_vars

try:
    from omp_rpc import RpcClient
except ImportError:
    RpcClient = None

logger = logging.getLogger("mypai_daemon.executors.python")


async def execute_python_job(job: dict[str, Any]) -> dict[str, Any]:
    """Execute Python lambda expression or code block in-process using inlined attributes."""
    start_time = time.time()
    job = substitute_vars(job)
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

        duration = round(time.time() - start_time, 3)
        res_str = json.dumps(res) if isinstance(res, (dict, list)) else str(res)

        internal_vars = {
            "_RETURN_CODE": 0,
            "_OUTPUT": res_str,
            "_ERROR": "",
            "_OBJECT": res,
            "_HTTP_CODE": 0,
            "_DURATION": duration,
            "_JOB_ID": job.get("id", ""),
            "_JOB_NAME": name,
        }

        result_prompt_template = job.get("result_prompt") or ""
        if result_prompt_template:
            if "#" in result_prompt_template:
                final_output = substitute_vars(
                    result_prompt_template, extra_vars=internal_vars
                )
            else:
                final_output = f"{result_prompt_template}\n{res_str}"
        else:
            final_output = res_str

        dispatch_result_to_omp(result_action, final_output)

        return {
            "status": "success",
            "kind": "python",
            "action": code,
            "return_code": 0,
            "output": final_output,
            "error": "",
            "object": res,
            "duration_sec": duration,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("Python execution error for job '%s': %s", name, exc)
        duration = round(time.time() - start_time, 3)
        err_str = str(exc)
        internal_vars = {
            "_RETURN_CODE": 1,
            "_OUTPUT": "",
            "_ERROR": err_str,
            "_OBJECT": None,
            "_HTTP_CODE": 0,
            "_DURATION": duration,
            "_JOB_ID": job.get("id", ""),
            "_JOB_NAME": name,
        }

        result_prompt_template = (
            job.get("result_error_prompt") or job.get("result_prompt") or ""
        )
        if result_prompt_template:
            if "#" in result_prompt_template:
                final_output = substitute_vars(
                    result_prompt_template, extra_vars=internal_vars
                )
            else:
                final_output = f"{result_prompt_template}\n{err_str}"
        else:
            final_output = err_str

        dispatch_result_to_omp(result_action, final_output)

        return {
            "status": "error",
            "kind": "python",
            "action": code,
            "return_code": 1,
            "output": final_output,
            "error": err_str,
            "object": None,
            "duration_sec": duration,
        }
