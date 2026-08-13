"""WebSocket Manager and Endpoint for real-time WebUI streaming in mypai_daemon."""

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("mypai_daemon.ws")

router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections for WebUI real-time log & state streaming."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WebSocket client disconnected (%d total)", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a JSON message to all active WebSocket clients."""
        if not self.active_connections:
            return

        payload = json.dumps(message)
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:  # noqa: BLE001
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)


ws_manager = ConnectionManager()


@router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket stream endpoint for real-time dashboard updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data_text = await websocket.receive_text()
            try:
                msg = json.loads(data_text)
                action = msg.get("action")
                if action == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
            except Exception as exc:  # noqa: BLE001
                logger.debug("Received non-JSON websocket payload: %s (error: %s)", data_text, exc)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
