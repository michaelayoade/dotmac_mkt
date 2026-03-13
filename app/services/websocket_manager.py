"""WebSocket connection manager for real-time notifications."""

from __future__ import annotations

import json
import logging
from uuid import UUID

from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks active WebSocket connections per person."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(
        self, person_id: UUID, websocket: WebSocket, subprotocol: str | None = None
    ) -> None:
        """Accept and register a WebSocket connection."""
        if subprotocol:
            await websocket.accept(subprotocol=subprotocol)
        else:
            await websocket.accept()
        key = str(person_id)
        if key not in self._connections:
            self._connections[key] = set()
        self._connections[key].add(websocket)
        logger.debug("WebSocket connected: person=%s", person_id)

    def disconnect(self, person_id: UUID, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        key = str(person_id)
        connections = self._connections.get(key)
        if connections:
            connections.discard(websocket)
            if not connections:
                del self._connections[key]
        logger.debug("WebSocket disconnected: person=%s", person_id)

    async def send_to_person(self, person_id: UUID, data: dict) -> None:
        """Send a JSON message to all connections for a person."""
        key = str(person_id)
        connections = self._connections.get(key, set())
        dead: list[WebSocket] = []
        for ws in connections:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            connections.discard(ws)
        if key in self._connections and not self._connections[key]:
            del self._connections[key]

    async def broadcast(self, data: dict) -> None:
        """Send a JSON message to all connected clients."""
        for person_id in list(self._connections.keys()):
            await self.send_to_person(UUID(person_id), data)

    def get_connection_count(self, person_id: UUID | None = None) -> int:
        """Get the number of active connections."""
        if person_id is not None:
            return len(self._connections.get(str(person_id), set()))
        return sum(len(conns) for conns in self._connections.values())


# Singleton instance
ws_manager = ConnectionManager()
