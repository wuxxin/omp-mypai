#!/usr/bin/env python3
"""MCP tool server for Nanobot Signal messaging integration."""

import json
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chat-channel")

SIGNAL_API_URL = os.getenv("SIGNAL_HTTP_URL", "http://localhost:50889")
NANOBOT_API_URL = os.getenv("NANOBOT_API_URL", "http://localhost:8790")
SIGNAL_ACCOUNT = os.getenv("SIGNAL_ACCOUNT", "")


def _http_request(
    url: str, method: str = "GET", data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Helper to perform HTTP requests to local REST endpoints."""
    req_data = json.dumps(data).encode("utf-8") if data else None
    headers = {"Content-Type": "application/json"} if req_data else {}
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        return {"error": f"HTTP {e.code}: {e.reason}", "details": error_body}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def get_pending_signal_messages(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch unread/pending Signal messages from the Nanobot buffer or signal-cli daemon."""
    # Attempt Nanobot queue first
    res = _http_request(f"{NANOBOT_API_URL}/api/signal/pending?limit={limit}")
    if "error" not in res and isinstance(res, list):
        return res

    # Fallback to signal-cli-rest-api receive endpoint
    url = (
        f"{SIGNAL_API_URL}/v1/receive/{SIGNAL_ACCOUNT}"
        if SIGNAL_ACCOUNT
        else f"{SIGNAL_API_URL}/v1/receive"
    )
    resp = _http_request(url)
    if isinstance(resp, list):
        return resp[:limit]
    return [resp] if isinstance(resp, dict) and "error" not in resp else []


@mcp.tool()
def send_signal_message(
    recipient: str, message: str, attachments: list[str] | None = None
) -> dict[str, Any]:
    """Send an outbound message via Signal to a recipient phone number or group ID."""
    payload: dict[str, Any] = {
        "message": message,
        "number": SIGNAL_ACCOUNT,
        "recipients": [recipient],
    }
    if attachments:
        payload["base64_attachments"] = attachments

    url = f"{SIGNAL_API_URL}/v2/send"
    return _http_request(url, method="POST", data=payload)


@mcp.tool()
def list_signal_chats() -> dict[str, Any]:
    """List registered Signal contacts and groups from signal-cli."""
    url = (
        f"{SIGNAL_API_URL}/v1/contacts/{SIGNAL_ACCOUNT}"
        if SIGNAL_ACCOUNT
        else f"{SIGNAL_API_URL}/v1/contacts"
    )
    return _http_request(url)


if __name__ == "__main__":
    mcp.run(transport="stdio")
