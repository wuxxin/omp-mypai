"""OMP RPC Job Executor using mandatory omp_rpc.RpcClient SDK with inlined job attributes."""

import json
import logging
import os
import time
from typing import Any

from mypai_tools.tools import substitute_vars

try:
    from omp_rpc import RpcClient
except ImportError:
    RpcClient = None

logger = logging.getLogger("mypai_daemon.executors.omp_rpc")


async def execute_omp_rpc_job(
    job: dict[str, Any], default_rpc_url: str = "", client: Any | None = None
) -> dict[str, Any]:
    """Execute an RPC job via omp_rpc.RpcClient using inlined attributes.

    Inlined Job Attributes:
    - action: RPC operation verb ('prompt' / 'prompt_and_wait', 'steer', 'followup', 'abort_and_prompt', 'switch_session', 'branch')
    - kwargs: keyword arguments dictionary containing 'prompt' string
    - args: positional argument list/tuple for custom RPC requests
    - result_prompt: optional fallback prompt text context
    """
    start_time = time.time()
    job = substitute_vars(job)
    name = job.get("name", "Unnamed RPC Job")
    action = (job.get("action") or "prompt").lower()

    kwargs_raw = job.get("kwargs") or {}
    rpc_kwargs: dict[str, Any] = {}
    if isinstance(kwargs_raw, str) and kwargs_raw.strip():
        try:
            rpc_kwargs = json.loads(kwargs_raw)
        except Exception:  # noqa: BLE001
            rpc_kwargs = {"raw": kwargs_raw}
    elif isinstance(kwargs_raw, dict):
        rpc_kwargs = dict(kwargs_raw)

    args_raw = job.get("args") or []
    rpc_args: list[Any] = []
    if isinstance(args_raw, str) and args_raw.strip():
        try:
            rpc_args = json.loads(args_raw)
        except Exception:  # noqa: BLE001
            rpc_args = [args_raw]
    elif isinstance(args_raw, list):
        rpc_args = args_raw

    # Extract RPC prompt from kwargs["prompt"], args[0], or result_prompt
    prompt = ""
    if isinstance(rpc_kwargs, dict) and "prompt" in rpc_kwargs:
        prompt = str(rpc_kwargs.pop("prompt"))
    elif rpc_args and isinstance(rpc_args[0], str):
        prompt = rpc_args[0]
    else:
        prompt = job.get("result_prompt") or ""

    logger.info("Executing OMP RPC job '%s' (action: %s)...", name, action)

    def _dispatch_on_client(rpc_c: Any) -> dict[str, Any]:
        if action in ("prompt", "prompt_and_wait"):
            res = rpc_c.prompt_and_wait(prompt, timeout=120.0)
            output = (
                res.require_assistant_text()
                if hasattr(res, "require_assistant_text")
                else str(res)
            )
            raw_obj = res
        elif action == "steer":
            rpc_c.steer(prompt)
            output = f"Steered: {prompt}"
            raw_obj = {"steered": prompt}
        elif action == "followup":
            rpc_c.follow_up(prompt)
            output = f"Follow-up queued: {prompt}"
            raw_obj = {"followup": prompt}
        elif action == "abort_and_prompt":
            rpc_c.abort_and_prompt(prompt)
            output = f"Aborted and prompted: {prompt}"
            raw_obj = {"aborted_and_prompted": prompt}
        elif action == "switch_session":
            res_raw = rpc_c.request_raw(action, *rpc_args, **rpc_kwargs)
            output = json.dumps(res_raw)
            raw_obj = res_raw
        else:
            rpc_c.prompt(prompt)
            output = f"Prompt queued: {prompt}"
            raw_obj = {"prompted": prompt}

        duration = round(time.time() - start_time, 3)
        return {
            "status": "success",
            "kind": "omp",
            "action": action,
            "return_code": 0,
            "output": output,
            "error": "",
            "object": raw_obj,
            "duration_sec": duration,
        }

    if client is not None:
        try:
            return _dispatch_on_client(client)
        except Exception as client_exc:  # noqa: BLE001
            logger.warning(
                "Persistent RPC client call failed: %s. Retrying with new client...",
                client_exc,
            )

    if RpcClient is None:
        duration = round(time.time() - start_time, 3)
        return {
            "status": "error",
            "kind": "omp",
            "action": action,
            "return_code": 1,
            "output": "",
            "error": "omp_rpc Python package is not installed.",
            "object": None,
            "duration_sec": duration,
        }

    target_cwd = job.get("agent_dir") or os.getenv("MYPAI_AGENT_DIR", "")
    rpc_client_kwargs: dict[str, Any] = {"extra_args": ["--auto-approve", "--continue"]}
    if target_cwd and os.path.isdir(target_cwd):
        rpc_client_kwargs["cwd"] = target_cwd

    try:
        with RpcClient(**rpc_client_kwargs) as temp_client:
            temp_client.install_headless_ui()
            return _dispatch_on_client(temp_client)
    except Exception as exc:  # noqa: BLE001
        logger.error("RPC execution error for job '%s': %s", name, exc)
        duration = round(time.time() - start_time, 3)
        return {
            "status": "error",
            "kind": "omp",
            "action": action,
            "return_code": 1,
            "output": "",
            "error": str(exc),
            "object": None,
            "duration_sec": duration,
        }


def dispatch_result_to_omp(result_action: str, final_output: str) -> None:
    """Helper to dispatch job output or error text to active OMP session via RpcClient."""
    act = (result_action or "ignore").lower()
    if act == "ignore" or not final_output or RpcClient is None:
        return

    try:
        with RpcClient() as client:
            client.install_headless_ui()
            if act == "prompt":
                client.prompt(final_output)
            elif act == "steer":
                client.steer(final_output)
            elif act == "followup":
                client.follow_up(final_output)
            elif act == "abort_and_prompt":
                client.abort_and_prompt(final_output)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to route output to OMP via RpcClient: %s", exc)
