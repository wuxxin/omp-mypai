#!/usr/bin/env python3
"""Shared SignalClient SDK for mypai_daemon and chat_mcp."""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("mypai_signal_client")


class SignalClient:
    """SDK for interacting with signal-cli-rest-api service."""

    def __init__(
        self,
        api_url: str | None = None,
        account: str | None = None,
        allowed_sender: str | None = None,
    ) -> None:
        self.api_url = api_url or os.getenv("SIGNAL_HTTP_URL", "http://localhost:50889")
        self.account = account or os.getenv("SIGNAL_ACCOUNT", "")
        self.allowed_sender = allowed_sender or os.getenv("SIGNAL_ALLOWED_SENDER", "")

    def _http_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any] | list[Any]:
        """Perform HTTP JSON request to signal-cli-rest-api."""
        url = f"{self.api_url.rstrip('/')}/{endpoint.lstrip('/')}"
        req_data = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {"Content-Type": "application/json"} if req_data else {}
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            error_body = e.fp.read().decode("utf-8") if e.fp else ""
            logger.error("Signal API HTTPError %d on %s %s: %s", e.code, method, url, error_body)
            return {"error": f"HTTP {e.code}: {e.reason}", "details": error_body}
        except urllib.error.URLError as e:
            logger.error("Signal API URLError on %s %s: %s", method, url, e.reason)
            return {"error": f"URLError: {e.reason}"}
        except Exception as e:  # noqa: BLE001
            logger.error("Signal API unexpected error on %s %s: %s", method, url, e)
            return {"error": str(e)}

    def is_sender_allowed(self, sender: str) -> bool:
        """Check if incoming sender matches allowed sender whitelist."""
        if not self.allowed_sender:
            return True
        clean_sender = sender.strip().lstrip("+")
        clean_allowed = self.allowed_sender.strip().lstrip("+")
        return clean_sender == clean_allowed or sender == self.allowed_sender

    def send_read_receipt(self, recipient: str, timestamps: list[int]) -> dict[str, Any]:
        """Send POST /v1/receipts/<account> to display two white checkmarks 🗸🗸."""
        if not recipient or not timestamps:
            return {"status": "skipped"}
        account_path = f"v1/receipts/{self.account}" if self.account else "v1/receipts"
        payload = {
            "recipient": recipient,
            "timestamps": timestamps,
            "receipt_type": "read",
        }
        res = self._http_request(account_path, method="POST", data=payload)
        return res if isinstance(res, dict) else {"status": "ok"}

    def send_typing_indicator(self, recipient: str) -> dict[str, Any]:
        """Send POST /v1/typing-indicator/<account> to display 'Typing...' status."""
        if not recipient:
            return {"status": "skipped"}
        account_path = (
            f"v1/typing-indicator/{self.account}"
            if self.account
            else "v1/typing-indicator"
        )
        payload = {"recipient": recipient}
        res = self._http_request(account_path, method="POST", data=payload)
        return res if isinstance(res, dict) else {"status": "ok"}

    def fetch_unread_messages(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch unread/pending Signal messages."""
        endpoint = (
            f"v1/receive/{self.account}" if self.account else "v1/receive"
        )
        res = self._http_request(endpoint, method="GET")
        if isinstance(res, list):
            return res[:limit]
        if isinstance(res, dict) and "error" not in res:
            return [res]
        return []

    def fetch_next_unread_message(
        self,
        sender: str | None = None,
        attachment_dir: str | None = None,
    ) -> dict[str, Any]:
        """Fetch oldest unread message (FIFO) matching allowed sender filter.
        
        Triggers read receipt (2 checkmarks) and typing indicator before returning.
        Extracted attachments are saved to attachment_dir ($PROJECT_DIR/scratch/signal_attachments).
        """
        raw_messages = self.fetch_unread_messages(limit=20)
        target_sender = sender or self.allowed_sender

        selected_msg = None
        selected_sender = ""
        msg_timestamp = 0

        for item in raw_messages:
            env = item.get("envelope", {}) if isinstance(item, dict) else {}
            item_sender = (
                env.get("sourceNumber")
                or env.get("source")
                or env.get("sourceUuid")
                or item.get("sender", "")
            )
            if target_sender and not self.is_sender_allowed(item_sender):
                logger.info("Ignoring Signal message from unauthorized sender '%s'", item_sender)
                continue

            selected_msg = item
            selected_sender = item_sender
            data_msg = env.get("dataMessage", {}) if isinstance(env, dict) else {}
            msg_timestamp = data_msg.get("timestamp") or env.get("timestamp", 0)
            break

        if not selected_msg:
            return {"status": "empty", "message": "No unread Signal messages."}

        # 1. Trigger Read Receipt & Typing Indicator
        if selected_sender and msg_timestamp:
            self.send_read_receipt(selected_sender, [msg_timestamp])
            self.send_typing_indicator(selected_sender)

        # 2. Extract Message Text & Attachments
        env = selected_msg.get("envelope", {}) if isinstance(selected_msg, dict) else {}
        data_msg = env.get("dataMessage", {}) if isinstance(env, dict) else {}
        text = data_msg.get("message", "") or selected_msg.get("message", "")

        raw_attachments = data_msg.get("attachments", []) or selected_msg.get("attachments", [])
        processed_attachments = []

        if raw_attachments:
            target_dir = attachment_dir or os.path.expanduser("~/agent-shared/mypai-workspace/scratch/signal_attachments")
            os.makedirs(target_dir, exist_ok=True)

            for idx, att in enumerate(raw_attachments):
                if isinstance(att, dict):
                    fname = att.get("filename") or f"att_{msg_timestamp}_{idx}.bin"
                    stored_path = att.get("storedFilename") or att.get("path")
                    content_type = att.get("contentType", "application/octet-stream")
                    size_bytes = att.get("size", 0)

                    target_path = os.path.join(target_dir, f"{msg_timestamp}_{fname}")
                    if stored_path and os.path.isfile(stored_path):
                        try:
                            with open(stored_path, "rb") as rf, open(target_path, "wb") as wf:
                                wf.write(rf.read())
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Failed to copy attachment %s: %s", stored_path, exc)
                            target_path = stored_path
                    
                    processed_attachments.append({
                        "filename": fname,
                        "content_type": content_type,
                        "file_path": target_path,
                        "size_bytes": size_bytes,
                    })

        return {
            "status": "success",
            "sender": selected_sender,
            "message": text,
            "timestamp": msg_timestamp,
            "attachments": processed_attachments,
            "remaining_unread_count": max(0, len(raw_messages) - 1),
        }

    def send_message(
        self,
        recipient: str | None = None,
        text: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        """Dispatch outbound message via Signal POST /v2/send."""
        target_recipient = recipient or self.allowed_sender
        if not target_recipient:
            return {"error": "No target recipient or SIGNAL_ALLOWED_SENDER configured."}

        payload: dict[str, Any] = {
            "message": text,
            "number": self.account,
            "recipients": [target_recipient],
        }

        if attachments:
            base64_files = []
            for path in attachments:
                abs_path = os.path.abspath(os.path.expanduser(path))
                if os.path.isfile(abs_path):
                    import base64
                    with open(abs_path, "rb") as f:
                        encoded = base64.b64encode(f.read()).decode("utf-8")
                        base64_files.append(encoded)
            payload["base64_attachments"] = base64_files

        res = self._http_request("v2/send", method="POST", data=payload)
        return res if isinstance(res, dict) else {"status": "sent"}

    def list_chats(self) -> dict[str, Any]:
        """Fetch registered contacts and groups via GET /v1/contacts."""
        endpoint = f"v1/contacts/{self.account}" if self.account else "v1/contacts"
        res = self._http_request(endpoint, method="GET")
        return res if isinstance(res, dict) else {"chats": res}
