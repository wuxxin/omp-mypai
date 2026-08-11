"""Tests for WebSocket real-time log streaming."""

import json


def test_websocket_ping_pong(test_client) -> None:
    with test_client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_text(json.dumps({"action": "ping"}))
        data = websocket.receive_text()
        assert json.loads(data) == {"event": "pong"}
