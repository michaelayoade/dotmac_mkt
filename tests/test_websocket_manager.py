"""Tests for WebSocket connection manager."""

import uuid
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from starlette.websockets import WebSocketState

from app.services.websocket_manager import ConnectionManager


@pytest.fixture()
def manager():
    return ConnectionManager()


def _make_ws(connected: bool = True) -> MagicMock:
    """Create a mock WebSocket."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    type(ws).client_state = PropertyMock(
        return_value=WebSocketState.CONNECTED
        if connected
        else WebSocketState.DISCONNECTED
    )
    return ws


class TestConnectionManager:
    @pytest.mark.asyncio
    async def test_connect(self, manager):
        person_id = uuid.uuid4()
        ws = _make_ws()
        await manager.connect(person_id, ws)
        assert manager.get_connection_count(person_id) == 1
        ws.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_with_subprotocol(self, manager):
        person_id = uuid.uuid4()
        ws = _make_ws()
        token = "header.jwt.token"
        await manager.connect(person_id, ws, subprotocol=token)
        assert manager.get_connection_count(person_id) == 1
        ws.accept.assert_called_once_with(subprotocol=token)

    @pytest.mark.asyncio
    async def test_disconnect(self, manager):
        person_id = uuid.uuid4()
        ws = _make_ws()
        await manager.connect(person_id, ws)
        manager.disconnect(person_id, ws)
        assert manager.get_connection_count(person_id) == 0

    @pytest.mark.asyncio
    async def test_send_to_person(self, manager):
        person_id = uuid.uuid4()
        ws = _make_ws()
        await manager.connect(person_id, ws)
        await manager.send_to_person(person_id, {"type": "test"})
        ws.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_to_person_no_connections(self, manager):
        # Should not raise
        await manager.send_to_person(uuid.uuid4(), {"type": "test"})

    @pytest.mark.asyncio
    async def test_multiple_connections(self, manager):
        person_id = uuid.uuid4()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await manager.connect(person_id, ws1)
        await manager.connect(person_id, ws2)
        assert manager.get_connection_count(person_id) == 2

        await manager.send_to_person(person_id, {"type": "multi"})
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast(self, manager):
        p1 = uuid.uuid4()
        p2 = uuid.uuid4()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await manager.connect(p1, ws1)
        await manager.connect(p2, ws2)

        await manager.broadcast({"type": "broadcast"})
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_dead_connection_cleanup(self, manager):
        person_id = uuid.uuid4()
        ws = _make_ws()
        ws.send_text.side_effect = RuntimeError("connection closed")
        await manager.connect(person_id, ws)

        await manager.send_to_person(person_id, {"type": "fail"})
        assert manager.get_connection_count(person_id) == 0

    def test_get_connection_count_total(self, manager):
        assert manager.get_connection_count() == 0
