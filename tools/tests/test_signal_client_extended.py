"""Hermetic unit tests for SignalClient SDK using unittest.mock."""

import json
from unittest.mock import MagicMock, patch
from mypai_tools.signal_client import SignalClient


def test_signal_client_send_read_receipt_and_typing() -> None:
    client = SignalClient(
        api_url="http://localhost:50889",
        account="+15550001111",
        allowed_sender="+15559992222",
    )

    with patch.object(client, "_http_request", return_value={"status": "ok"}) as mock_req:
        res_receipt = client.send_read_receipt("+15559992222", [1723420000000])
        assert res_receipt == {"status": "ok"}
        mock_req.assert_called_with(
            "v1/receipts/+15550001111",
            method="POST",
            data={
                "recipient": "+15559992222",
                "timestamps": [1723420000000],
                "receipt_type": "read",
            },
        )

        res_typing = client.send_typing_indicator("+15559992222")
        assert res_typing == {"status": "ok"}
        mock_req.assert_called_with(
            "v1/typing-indicator/+15550001111",
            method="POST",
            data={"recipient": "+15559992222"},
        )


def test_signal_client_send_message() -> None:
    client = SignalClient(
        api_url="http://localhost:50889",
        account="+15550001111",
        allowed_sender="+15559992222",
    )

    with patch.object(client, "_http_request", return_value={"status": "sent"}) as mock_req:
        res = client.send_message(recipient="+15559992222", text="Hello back!")
        assert res == {"status": "sent"}
        mock_req.assert_called_once_with(
            "v2/send",
            method="POST",
            data={
                "message": "Hello back!",
                "number": "+15550001111",
                "recipients": ["+15559992222"],
            },
        )


def test_signal_client_fetch_next_unread_message(tmp_path) -> None:
    client = SignalClient(
        api_url="http://localhost:50889",
        account="+15550001111",
        allowed_sender="+15559992222",
    )

    sample_msg = [
        {
            "envelope": {
                "sourceNumber": "+15559992222",
                "timestamp": 1723420000000,
                "dataMessage": {
                    "timestamp": 1723420000000,
                    "message": "Hello Signal Agent!",
                    "attachments": [],
                },
            }
        }
    ]

    with patch.object(client, "_http_request") as mock_req:
        mock_req.side_effect = lambda endpoint, method="GET", data=None: (
            sample_msg if "receive" in endpoint else {"status": "ok"}
        )

        res = client.fetch_next_unread_message(attachment_dir=str(tmp_path))
        assert res["status"] == "success"
        assert res["sender"] == "+15559992222"
        assert res["message"] == "Hello Signal Agent!"
        assert res["timestamp"] == 1723420000000
