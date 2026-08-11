#!/usr/bin/env python3
"""Nanobot Signal Gateway RPC Bridge.

Listens for incoming Signal messages via the Nanobot Signal Gateway (signal-cli),
recalls sender/global memory context from Hindsight REST API, calls the persistent
OMP agent service over RPC, and dispatches agent responses back via Signal.
"""

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

# Import chat_mcp helpers if available
try:
    from mypai_tools.chat_mcp import (
        get_pending_signal_messages,
        send_signal_message,
    )
except ImportError:
    try:
        from chat_mcp import (
            get_pending_signal_messages,
            send_signal_message,
        )
    except ImportError:
        get_pending_signal_messages = None
        send_signal_message = None

# Configuration & Constants
SIGNAL_API_URL = os.getenv("SIGNAL_HTTP_URL", "http://localhost:50889")
NANOBOT_API_URL = os.getenv("NANOBOT_API_URL", "http://localhost:8790")
SIGNAL_ACCOUNT = os.getenv("SIGNAL_ACCOUNT", "")
HINDSIGHT_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
HINDSIGHT_BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "omp-orchestrator")
MYPAI_RPC_URL = os.getenv("MYPAI_RPC_URL", "http://localhost:52080/v1/rpc")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chat_bridge")


def _http_request(
    url: str,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Helper for JSON HTTP requests with explicit exception handling."""
    req_data = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if req_data else {}
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = ""
        if e.fp:
            try:
                error_body = e.fp.read().decode("utf-8")
            except Exception:  # noqa: BLE001, S110
                pass
        logger.error(f"HTTPError {e.code} on {method} {url}: {e.reason} - {error_body}")
        return {"error": f"HTTP {e.code}: {e.reason}", "details": error_body}
    except urllib.error.URLError as e:
        logger.error(f"URLError on {method} {url}: {e.reason}")
        return {"error": f"URLError: {e.reason}"}
    except Exception as e:  # noqa: BLE001
        logger.error(f"Unexpected error on {method} {url}: {e}")
        return {"error": str(e)}


def fetch_pending_messages(limit: int = 10) -> list[dict[str, Any]]:
    """Retrieve unread/pending Signal messages via nanobot_mcp or REST API endpoints."""
    if get_pending_signal_messages is not None:
        try:
            res = get_pending_signal_messages(limit=limit)
            if isinstance(res, list):
                return res
        except Exception as e:  # noqa: BLE001
            logger.warning(f"nanobot_mcp get_pending_signal_messages failed: {e}")

    # Fallback to direct HTTP fetch from Nanobot API first
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
    if isinstance(resp, dict) and "error" not in resp:
        return [resp]
    return []


def extract_message_info(raw_msg: dict[str, Any]) -> tuple[str, str, str] | None:
    """Extract (sender, message_text, message_id) from raw message structure.

    Returns None if message format is unrecognized or message body is empty.
    """
    sender = ""
    text = ""
    msg_id = ""

    # Check signal-cli-rest-api envelope structure
    if "envelope" in raw_msg and isinstance(raw_msg["envelope"], dict):
        env = raw_msg["envelope"]
        sender = (
            env.get("source") or env.get("sourceNumber") or env.get("sourceUuid") or ""
        )
        timestamp = env.get("timestamp", "")
        data_msg = env.get("dataMessage")
        if isinstance(data_msg, dict):
            text = data_msg.get("message", "")
            msg_id = f"{sender}_{timestamp}_{data_msg.get('timestamp', '')}"
        else:
            msg_id = f"{sender}_{timestamp}"
    else:
        # Check direct JSON structure (Nanobot queue format)
        sender = (
            raw_msg.get("sender")
            or raw_msg.get("source")
            or raw_msg.get("recipient", "")
        )
        text = raw_msg.get("message") or raw_msg.get("text") or raw_msg.get("body", "")
        msg_id = str(
            raw_msg.get("id") or raw_msg.get("uuid") or hash(f"{sender}:{text}")
        )

    sender = sender.strip()
    text = text.strip()

    if not sender or not text:
        return None

    # Ignore messages sent by self if SIGNAL_ACCOUNT matches sender
    if SIGNAL_ACCOUNT and sender == SIGNAL_ACCOUNT:
        return None

    return sender, text, msg_id


def query_hindsight_context(sender: str, prompt: str) -> str:
    """Query Hindsight REST API for sender-specific or global memory context."""
    url = f"{HINDSIGHT_URL}/v1/default/banks/{HINDSIGHT_BANK_ID}/recall"
    payload = {
        "query": f"Sender {sender}: {prompt}",
        "top_k": 5,
    }

    logger.info(f"Querying Hindsight memory bank '{HINDSIGHT_BANK_ID}'...")
    res = _http_request(url, method="POST", data=payload, timeout=10.0)

    if "error" in res:
        logger.warning(f"Hindsight recall error: {res.get('error')}")
        return ""

    recalled_items: list[str] = []
    # Handle various possible response schemas from Hindsight REST API
    memories = res.get("results") or res.get("memories") or res.get("documents") or []
    if isinstance(memories, list):
        for item in memories:
            if isinstance(item, str):
                recalled_items.append(item)
            elif isinstance(item, dict):
                content = item.get("content") or item.get("text") or item.get("fact")
                if content:
                    recalled_items.append(str(content))

    if recalled_items:
        context_str = "\n".join(f"- {item}" for item in recalled_items)
        logger.info(
            f"Recalled {len(recalled_items)} memory context item(s) from Hindsight."
        )
        return context_str

    return ""


def poke_omp_agent(prompt: str, context: str, sender: str) -> str:
    """Send an RPC poke to the persistent OMP agent service with prompt and recalled context."""
    payload = {
        "jsonrpc": "2.0",
        "method": "agent_poke",
        "params": {
            "prompt": prompt,
            "context": context,
            "sender": sender,
            "channel": "signal",
        },
        "id": str(uuid.uuid4()),
    }

    logger.info(f"Sending RPC poke to MyPAI agent at {MYPAI_RPC_URL}...")
    res = _http_request(MYPAI_RPC_URL, method="POST", data=payload, timeout=30.0)

    if "error" in res:
        logger.error(f"OMP Agent RPC call failed: {res.get('error')}")
        return f"[OMP Gateway Error] Agent service RPC failed: {res.get('error')}"

    # Parse response from standard JSON-RPC or REST RPC payload
    result = res.get("result")
    if isinstance(result, dict):
        return (
            result.get("response")
            or result.get("text")
            or result.get("output")
            or json.dumps(result)
        )
    elif isinstance(result, str):
        return result
    elif "response" in res:
        return str(res["response"])

    return (
        str(result)
        if result is not None
        else "[OMP Gateway Error] Empty response from agent RPC."
    )


def dispatch_signal_response(recipient: str, message: str) -> dict[str, Any]:
    """Dispatch outbound message via nanobot_mcp or direct signal-cli endpoint."""
    if send_signal_message is not None:
        try:
            res = send_signal_message(recipient=recipient, message=message)
            if "error" not in res:
                logger.info(
                    f"Dispatched Signal message to {recipient} via nanobot_mcp."
                )
                return res
            logger.warning(
                f"nanobot_mcp send failed: {res.get('error')}, falling back to direct HTTP."
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"nanobot_mcp exception: {e}, falling back to direct HTTP.")

    # Direct HTTP dispatch to signal-cli /v2/send
    payload: dict[str, Any] = {
        "message": message,
        "number": SIGNAL_ACCOUNT,
        "recipients": [recipient],
    }
    url = f"{SIGNAL_API_URL}/v2/send"
    res = _http_request(url, method="POST", data=payload, timeout=15.0)
    if "error" not in res:
        logger.info(f"Dispatched Signal message to {recipient} via signal-cli HTTP.")
    else:
        logger.error(
            f"Failed to dispatch Signal message to {recipient}: {res.get('error')}"
        )
    return res


def process_signal_message(raw_msg: dict[str, Any]) -> bool:
    """Process a single incoming Signal message through the Hindsight RPC bridge pipeline."""
    info = extract_message_info(raw_msg)
    if not info:
        return False

    sender, prompt, _msg_id = info
    logger.info(f"Processing incoming message from '{sender}': {prompt[:50]}...")

    # 1. Query Hindsight memory context
    context = query_hindsight_context(sender=sender, prompt=prompt)

    # 2. Poke OMP agent RPC
    agent_response = poke_omp_agent(prompt=prompt, context=context, sender=sender)

    # 3. Dispatch agent response back via Signal
    dispatch_signal_response(recipient=sender, message=agent_response)
    return True


def run_bridge(poll_interval: float = 3.0, run_once: bool = False) -> None:
    """Main daemon loop for listening to incoming Signal messages and bridging them to OMP."""
    logger.info("Starting Nanobot Signal Gateway RPC Bridge daemon...")
    logger.info(f"Signal Gateway: {SIGNAL_API_URL} | Nanobot: {NANOBOT_API_URL}")
    logger.info(f"Hindsight Bank: {HINDSIGHT_BANK_ID} ({HINDSIGHT_URL})")
    logger.info(f"MyPAI RPC Endpoint: {MYPAI_RPC_URL}")

    seen_msg_ids: set[str] = set()

    try:
        while True:
            messages = fetch_pending_messages()
            for raw_msg in messages:
                info = extract_message_info(raw_msg)
                if not info:
                    continue
                _, _, msg_id = info
                if msg_id in seen_msg_ids:
                    continue
                seen_msg_ids.add(msg_id)

                try:
                    process_signal_message(raw_msg)
                except Exception:
                    logger.exception("Error processing message %s", msg_id)

            if run_once:
                break
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("Signal Gateway RPC Bridge stopped by user.")


def main() -> None:
    """Parse command-line arguments and run the bridge daemon."""
    parser = argparse.ArgumentParser(
        description="Nanobot Signal Gateway RPC Bridge for OMP Agent."
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=3.0,
        help="Polling interval in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process current pending messages once and exit",
    )
    args = parser.parse_args()

    run_bridge(poll_interval=args.poll_interval, run_once=args.once)


if __name__ == "__main__":
    main()
