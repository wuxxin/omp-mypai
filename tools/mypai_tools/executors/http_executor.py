"""HTTP Job Executor supporting GET, POST, PUT, DELETE, PATCH with inlined job attributes."""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("mypai_heartbeat.http_executor")


async def execute_http_job(job: dict[str, Any]) -> dict[str, Any]:
    """Execute HTTP requests using inlined attributes.

    Inlined Attributes:
    - type: 'http'
    - action: HTTP method verb ('GET', 'POST', 'PUT', 'DELETE', 'PATCH')
    - url: target API endpoint URL
    - kwargs: dictionary containing body parameters and optional 'headers' dictionary
    - args: optional positional body payload dictionary or raw string
    - output_prompt: optional human-readable task description
    """
    name = job.get("name", "Unnamed HTTP Job")
    action = job.get("action") or "GET"
    method = str(action).upper()

    url = job.get("url") or job.get("output_prompt") or ""
    if not url:
        raise ValueError("No target URL specified in 'url' attribute.")

    hindsight_url = os.getenv("HINDSIGHT_API_URL", "http://localhost:8888")
    hindsight_bank = os.getenv("HINDSIGHT_BANK_ID", "omp-orchestrator")
    omp_rpc_url = os.getenv("OMP_RPC_URL", "http://localhost:51080/v1/rpc")

    url = url.replace("{HINDSIGHT_API_URL}", hindsight_url)
    url = url.replace("{HINDSIGHT_BANK_ID}", hindsight_bank)
    url = url.replace("{OMP_RPC_URL}", omp_rpc_url)

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

    headers = {"Content-Type": "application/json"}
    if "headers" in kwargs and isinstance(kwargs["headers"], dict):
        headers.update(kwargs.pop("headers"))
    elif job.get("headers") and isinstance(job["headers"], dict):
        headers.update(job["headers"])

    # Determine request payload: use kwargs remaining dict or args
    payload = kwargs if kwargs else job.get("args")
    if isinstance(payload, str) and payload.strip():
        try:
            payload = json.loads(payload)
        except Exception:  # noqa: BLE001, S110
            pass

    logger.info("Executing HTTP %s request to %s...", method, url)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method, url, json=payload if payload else None, headers=headers
        )
        resp.raise_for_status()

        try:
            res_data = resp.json()
            output_str = json.dumps(res_data)
        except Exception:  # noqa: BLE001
            output_str = resp.text

        logger.info("HTTP %s '%s' returned status %d", method, name, resp.status_code)
        return {
            "status": "success",
            "http_code": resp.status_code,
            "output": output_str,
        }
