"""Python Job Executor supporting in-process lambda expressions and async code."""

import asyncio
import contextlib
import inspect
import io
import json
import logging
import time
from typing import Any

from mypai_tools.executors.omp_rpc_executor import dispatch_result_to_omp
from mypai_tools.tools import (
    build_internal_vars,
    evaluate_and_dispatch_result_prompt,
    substitute_vars,
)

logger = logging.getLogger("mypai_daemon.executors.python")


async def execute_python_job(
    job: dict[str, Any],
    daemon_queue: Any | None = None,
    session_mgr: Any | None = None,
) -> dict[str, Any]:
    """Execute Python lambda expression or code snippet in-process with timeout protection."""
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
        except Exception:  # noqa: BLE001
            pass

    kwargs_val = job.get("kwargs") or {}
    if isinstance(kwargs_val, str) and kwargs_val.strip().startswith("{"):
        try:
            kwargs_val = json.loads(kwargs_val)
        except Exception:  # noqa: BLE001
            pass

    opts = job.get("opts") if isinstance(job.get("opts"), dict) else {}
    timeout_sec = float(opts.get("timeout_sec") or 5.0)

    logger.info("Executing Python job '%s' (timeout: %.1fs)...", name, timeout_sec)

    local_namespace: dict[str, Any] = {}
    global_namespace: dict[str, Any] = {
        "asyncio": asyncio,
        "job": job,
        "args": args_val,
        "kwargs": kwargs_val,
    }

    try:

        def _run_sync_code() -> Any:
            stdout_buf = io.StringIO()
            clean_code = code.strip()
            with contextlib.redirect_stdout(stdout_buf):
                if clean_code.startswith("lambda"):
                    fn = eval(clean_code, global_namespace, local_namespace)
                    try:
                        sig = inspect.signature(fn)
                        param_count = len(sig.parameters)
                    except (ValueError, TypeError):
                        param_count = 2

                    if param_count >= 2:
                        return fn(args_val, kwargs_val)
                    if param_count == 1:
                        return fn(args_val)
                    return fn()
                else:
                    exec(clean_code, global_namespace, local_namespace)  # noqa: S102
                    printed = stdout_buf.getvalue().strip()
                    return (
                        local_namespace.get("result")
                        or global_namespace.get("result")
                        or printed
                        or "Execution completed."
                    )

        res = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _run_sync_code),
            timeout=timeout_sec,
        )

        if asyncio.iscoroutine(res):
            res = await asyncio.wait_for(res, timeout=timeout_sec)

        duration = round(time.time() - start_time, 3)
        res_str = json.dumps(res) if isinstance(res, (dict, list)) else str(res)

        internal_vars = build_internal_vars(
            job,
            return_code=0,
            output=res_str,
            error="",
            obj=res,
            http_code=0,
            duration=duration,
        )

        final_output = evaluate_and_dispatch_result_prompt(
            job,
            internal_vars,
            is_success=True,
            default_output=res_str,
            daemon_queue=daemon_queue,
            session_mgr=session_mgr,
            dispatch_fn=dispatch_result_to_omp,
        )

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
        internal_vars = build_internal_vars(
            job,
            return_code=1,
            output="",
            error=err_str,
            obj=None,
            http_code=0,
            duration=duration,
        )

        final_output = evaluate_and_dispatch_result_prompt(
            job,
            internal_vars,
            is_success=False,
            default_output=err_str,
            daemon_queue=daemon_queue,
            session_mgr=session_mgr,
            dispatch_fn=dispatch_result_to_omp,
        )

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
