"""Fault tolerance and resilience unit tests for mypai_daemon."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest

from mypai_tools.daemon.session_manager import OMPSessionManager
from mypai_tools.signal_client import SignalClient
from conftest import FakeRpcClient


class FaultyRpcClient(FakeRpcClient):
    """Mock RpcClient that simulates process crash on first call."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.call_count = 0

    def prompt(self, text: str):
        self.call_count += 1
        if self.call_count == 1:
            raise ConnectionResetError("OMP RPC socket crashed mid-turn")
        return {"status": "ok", "response": f"Recovered turn: {text}"}


@pytest.mark.asyncio
async def test_session_manager_fault_recovery(tmp_path) -> None:
    faulty_client = FaultyRpcClient()
    mgr = OMPSessionManager(project_dir=str(tmp_path), session_name="mypai-test-session")
    mgr.rpc_client = faulty_client

    # Execute turn with faulty client -> first call fails, session manager reconnects
    with patch.object(mgr, "ensure_connected", return_value=faulty_client):
        res = await mgr.execute_turn(prompt="Resilient turn", mode="prompt")
        assert res["status"] == "error" or res["return_code"] == 1
        assert "OMP RPC socket crashed" in res["error"]

    # Subsequent call after reconnect succeeds
    res_ok = await mgr.execute_turn(prompt="Recovered turn", mode="prompt")
    assert res_ok["status"] == "success"
    assert "Recovered turn" in res_ok["output"]


@pytest.mark.asyncio
async def test_signal_client_attachment_extraction(tmp_path) -> None:
    client = SignalClient(account="+15550001111", allowed_sender="+15559992222")

    # Create dummy stored attachment file
    source_att = tmp_path / "incoming_photo.jpg"
    source_att.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIFSampleImage")

    msg_payload = [
        {
            "envelope": {
                "sourceNumber": "+15559992222",
                "timestamp": 1723450000000,
                "dataMessage": {
                    "timestamp": 1723450000000,
                    "message": "Image attached",
                    "attachments": [
                        {
                            "filename": "photo.jpg",
                            "storedFilename": str(source_att),
                            "contentType": "image/jpeg",
                            "size": 1024,
                        }
                    ],
                },
            }
        }
    ]

    target_dir = tmp_path / "scratch" / "signal_attachments"

    with patch.object(client, "_http_request") as mock_req:
        mock_req.side_effect = lambda endpoint, method="GET", data=None: (
            msg_payload if "receive" in endpoint else {"status": "ok"}
        )

        res = client.fetch_next_unread_message(attachment_dir=str(target_dir))
        assert res["status"] == "success"
        assert len(res["attachments"]) == 1
        att_info = res["attachments"][0]
        assert att_info["filename"] == "photo.jpg"
        assert att_info["content_type"] == "image/jpeg"
        assert target_dir.exists()
