"""HTTP Job Executor supporting GET, POST, PUT, DELETE, PATCH with inlined job attributes."""

import json
import logging
import time
from typing import Any

import httpx

from mypai_tools.executors.omp_rpc_executor import dispatch_result_to_omp
from mypai_tools.tools import build_internal_vars, substitute_vars

logger = logging.getLogger("mypai_daemon.executors.http")


async def execute_http_job(
    job: dict[str, Any],
    daemon_queue: Any | None = None,
    session_mgr: Any | None = None,
) -> dict[str, Any]:
    """Execute HTTP requests using inlined attributes.

    Inlined Attributes:
    - kind: 'http'
    - action: HTTP method verb ('GET', 'POST', 'PUT', 'DELETE', 'PATCH')
    - args: target API endpoint URL (or list of [URL, optional_payload])
    - kwargs: dictionary containing body parameters and optional 'headers' dictionary
    - result_prompt: optional result context template
    """
    start_time = time.time()
    job = substitute_vars(job)
    name = job.get("name", "Unnamed HTTP Job")
    action = job.get("action") or "GET"
    method = str(action).upper()

    args_raw = job.get("args") or []
    url = ""
    payload = None

    if isinstance(args_raw, str) and args_raw.strip():
        if args_raw.strip().startswith(("[", "{")):
            try:
                parsed_args = json.loads(args_raw)
                if isinstance(parsed_args, list) and parsed_args:
                    url = str(parsed_args[0])
                    if len(parsed_args) > 1:
                        payload = parsed_args[1]
                elif isinstance(parsed_args, str):
                    url = parsed_args
            except Exception:  # noqa: BLE001
                url = args_raw.strip()
        else:
            url = args_raw.strip()
    elif isinstance(args_raw, list) and args_raw:
        url = str(args_raw[0])
        if len(args_raw) > 1:
            payload = args_raw[1]

    if not url:
        duration = round(time.time() - start_time, 3)
        return {
            "status": "error",
            "kind": "http",
            "action": method,
            "return_code": 1,
            "output": "",
            "error": "No target URL specified in 'args' attribute.",
            "object": None,
            "duration_sec": duration,
        }

    # Extract headers and body payload from kwargs
    kwargs_raw = job.get("kwargs") or {}
    kwargs: dict[str, Any] = {}
    if isinstance(kwargs_raw, str) and kwargs_raw.strip():
        try:
            kwargs = json.loads(kwargs_raw)
        except Exception:  # noqa: BLE001, S110
            pass
    elif isinstance(kwargs_raw, dict):
        kwargs = dict(kwargs_raw)

    opts_raw = job.get("opts") or {}
    opts: dict[str, Any] = {}
    if isinstance(opts_raw, str) and opts_raw.strip():
        try:
            opts = json.loads(opts_raw)
        except Exception:  # noqa: BLE001, S110
            pass
    elif isinstance(opts_raw, dict):
        opts = dict(opts_raw)

    headers = {"Content-Type": "application/json"}
    if "headers" in opts and isinstance(opts["headers"], dict):
        headers.update(opts["headers"])
    if "headers" in kwargs and isinstance(kwargs["headers"], dict):
        headers.update(kwargs.pop("headers"))
    elif job.get("headers") and isinstance(job["headers"], dict):
        headers.update(job["headers"])

    if not payload and kwargs:
        payload = kwargs

    logger.info("Executing HTTP %s request to %s...", method, url)

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.request(
                method, url, json=payload if payload else None, headers=headers
            )
            duration = round(time.time() - start_time, 3)

            try:
                res_obj = resp.json()
                output_str = json.dumps(res_obj)
            except Exception:  # noqa: BLE001
                res_obj = resp.text
                output_str = resp.text

            is_success = resp.status_code < 400
            status_str = "success" if is_success else "error"
            error_str = "" if is_success else f"HTTP {resp.status_code}: {output_str}"

            logger.info(
                "HTTP %s '%s' returned status %d", method, name, resp.status_code
            )

            internal_vars = build_internal_vars(
                job,
                return_code=0 if is_success else resp.status_code,
                output=output_str,
                error=error_str,
                obj=res_obj,
                http_code=resp.status_code,
                duration=duration,
            )

            if not is_success:
                result_prompt_template = (
                    job.get("result_error_prompt") or job.get("result_prompt") or ""
                )
            else:
                result_prompt_template = job.get("result_prompt") or ""

            if isinstance(result_prompt_template, str):
                result_prompt_template = result_prompt_template.strip()

            if result_prompt_template:
                if "#" in result_prompt_template:
                    final_output = substitute_vars(
                        result_prompt_template, extra_vars=internal_vars
                    )
                else:
                    final_output = f"{result_prompt_template}\n{output_str if is_success else error_str}"
            else:
                final_output = output_str if is_success else error_str

            result_action = job.get("result_action") or ""
            dispatch_result_to_omp(
                result_action,
                final_output,
                daemon_queue=daemon_queue,
                session_mgr=session_mgr,
            )

            return {
                "status": status_str,
                "kind": "http",
                "action": method,
                "return_code": 0 if is_success else resp.status_code,
                "output": output_str,
                "error": error_str,
                "object": res_obj,
                "duration_sec": duration,
            }
    except Exception as exc:  # noqa: BLE001
        logger.error("HTTP execution error for job '%s': %s", name, exc)
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

        result_prompt_template = (
            job.get("result_error_prompt") or job.get("result_prompt") or ""
        )
        if isinstance(result_prompt_template, str):
            result_prompt_template = result_prompt_template.strip()
        if result_prompt_template:
            if "#" in result_prompt_template:
                final_output = substitute_vars(
                    result_prompt_template, extra_vars=internal_vars
                )
            else:
                final_output = f"{result_prompt_template}\n{err_str}"
        else:
            final_output = err_str

        result_action = job.get("result_action") or ""
        dispatch_result_to_omp(
            result_action,
            final_output,
            daemon_queue=daemon_queue,
            session_mgr=session_mgr,
        )

        return {
            "status": "error",
            "kind": "http",
            "action": method,
            "return_code": 1,
            "output": final_output,
            "error": err_str,
            "object": None,
            "duration_sec": duration,
        }
