"""OMP RPC Job Executor using daemon TurnQueue and OMPSessionManager."""

import asyncio
import logging
import time
from typing import Any

from mypai_tools.tools import extract_omp_prompt, substitute_vars

logger = logging.getLogger("mypai_daemon.executors.omp_rpc")


async def async_dispatch_result_to_omp(
    result_action: str,
    final_output: str,
    daemon_queue: Any | None = None,
    session_mgr: Any | None = None,
    job_id: str = "",
) -> None:
    """Route job output to active OMP session via TurnQueue with lineage tagging."""
    act = str(result_action or "log").lower().strip()
    if act in ("log", "ignore", "none", "") or not final_output:
        return

    if daemon_queue is not None:
        await daemon_queue.enqueue(
            prompt=final_output,
            mode=act,
            source="executor_result",
            is_result_call=True,
            origin_job_id=job_id,
        )
    elif session_mgr is not None:
        await session_mgr.execute_turn(prompt=final_output, mode=act)
    else:
        logger.warning(
            "Cannot dispatch result action '%s' to OMP: daemon_queue unavailable.",
            act,
        )


def dispatch_result_to_omp(
    result_action: str,
    final_output: str,
    daemon_queue: Any | None = None,
    session_mgr: Any | None = None,
    job_id: str = "",
) -> None:
    """Sync wrapper to dispatch job output to active OMP session via TurnQueue."""
    act = str(result_action or "log").lower().strip()
    if act in ("log", "ignore", "none", "") or not final_output:
        return

    try:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                async_dispatch_result_to_omp(
                    result_action,
                    final_output,
                    daemon_queue,
                    session_mgr,
                    job_id=job_id,
                )
            )
        except RuntimeError:
            asyncio.run(
                async_dispatch_result_to_omp(
                    result_action,
                    final_output,
                    daemon_queue,
                    session_mgr,
                    job_id=job_id,
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to dispatch result to OMP: %s", exc)


async def execute_omp_rpc_job(
    job: dict[str, Any],
    daemon_queue: Any | None = None,
    session_mgr: Any | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Execute an OMP RPC job via TurnQueue."""
    start_time = time.time()
    job = substitute_vars(job)
    name = job.get("name", "Unnamed RPC Job")
    action = (job.get("action") or "prompt").lower()

    prompt = extract_omp_prompt(job)
    if not prompt:
        duration = round(time.time() - start_time, 3)
        return {
            "status": "error",
            "kind": "omp",
            "action": action,
            "return_code": 1,
            "output": "",
            "error": f"Empty prompt string for OMP RPC job '{name}'.",
            "object": None,
            "duration_sec": duration,
        }

    logger.info("Executing OMP RPC job '%s' (action: %s)...", name, action)

    try:
        if daemon_queue is not None:
            item = await daemon_queue.enqueue(
                prompt=prompt,
                mode=action,
                source="cron",
                context=job,
                origin_job_id=job.get("id", ""),
            )
            duration = round(time.time() - start_time, 3)
            return {
                "status": "queued",
                "kind": "omp",
                "action": action,
                "return_code": 0,
                "output": f"Queued task {item['task_id']}",
                "error": "",
                "object": item,
                "duration_sec": duration,
            }

        if session_mgr is not None:
            res = await session_mgr.execute_turn(prompt=prompt, mode=action)
            duration = round(time.time() - start_time, 3)
            return {
                "status": res.get("status", "success"),
                "kind": "omp",
                "action": action,
                "return_code": res.get("return_code", 0),
                "output": res.get("output", ""),
                "error": res.get("error", ""),
                "object": res,
                "duration_sec": duration,
            }

        if client is not None:
            if action == "steer":
                client.steer(prompt)
            elif action in ("followup", "follow_up"):
                client.follow_up(prompt)
            elif action == "abort_and_prompt":
                client.abort_and_prompt(prompt)
            else:
                client.prompt(prompt)

            duration = round(time.time() - start_time, 3)
            return {
                "status": "success",
                "kind": "omp",
                "action": action,
                "return_code": 0,
                "output": f"RPC command '{action}' dispatched.",
                "error": "",
                "object": {"prompt": prompt},
                "duration_sec": duration,
            }

        raise RuntimeError("No daemon_queue or session_mgr available to execute OMP RPC job.")

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
