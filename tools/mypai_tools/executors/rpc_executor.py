"""RPC Job Executor using mandatory omp_rpc.RpcClient SDK with inlined job attributes."""

import json
import logging
from typing import Any

try:
    from omp_rpc import RpcClient
except ImportError:
    RpcClient = None

logger = logging.getLogger("mypai_heartbeat.rpc_executor")


async def execute_rpc_job(job: dict[str, Any], default_rpc_url: str = "") -> dict[str, Any]:
    """Execute an RPC job via omp_rpc.RpcClient using inlined attributes.

    Inlined Job Attributes:
    - action: RPC operation verb ('prompt' / 'prompt_and_wait', 'steer', 'followup', 'abort_and_prompt', 'switch_session', 'branch')
    - kwargs: keyword arguments dictionary containing 'prompt' string (e.g. kwargs: {"prompt": "..."})
    - args: positional argument list/tuple for custom RPC requests
    - result_prompt: optional fallback prompt text context
    """
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

    logger.info("Executing RPC job '%s' (action: %s)...", name, action)

    if RpcClient is None:
        raise RuntimeError("omp_rpc Python package is not installed.")

    try:
        with RpcClient() as client:
            client.install_headless_ui()

            if action in ("prompt", "prompt_and_wait"):
                res = client.prompt_and_wait(prompt, timeout=120.0)
                output = res.require_assistant_text() if hasattr(res, "require_assistant_text") else str(res)
                return {"status": "success", "action": action, "output": output}

            elif action == "steer":
                client.steer(prompt)
                return {"status": "success", "action": action, "output": f"Steered: {prompt}"}

            elif action in ("followup", "follow_up"):
                client.follow_up(prompt)
                return {"status": "success", "action": action, "output": f"Follow-up queued: {prompt}"}

            elif action == "abort_and_prompt":
                client.abort_and_prompt(prompt)
                return {"status": "success", "action": action, "output": f"Aborted and prompted: {prompt}"}

            elif action in ("switch_session", "branch"):
                res_raw = client.request_raw(action, *rpc_args, **rpc_kwargs)
                return {"status": "success", "action": action, "output": json.dumps(res_raw)}

            else:
                client.prompt(prompt)
                return {"status": "success", "action": action, "output": f"Prompt queued: {prompt}"}

    except Exception as exc:  # noqa: BLE001
        logger.error("RPC execution error for job '%s': %s", name, exc)
        return {"status": "error", "action": action, "error": str(exc)}
