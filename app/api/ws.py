"""WebSocket endpoint for real-time notifications."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.auth_flow import decode_access_token
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _authenticate_ws(token: str) -> str | None:
    """Validate JWT token and return person_id or None."""
    if not token:
        return None
    db: Session = SessionLocal()
    try:
        payload = decode_access_token(db, token)
        return payload.get("sub")
    except Exception:
        return None
    finally:
        db.close()


def _extract_ws_token(websocket: WebSocket) -> str:
    """Read JWT token from Sec-WebSocket-Protocol header."""
    raw_header = websocket.headers.get("sec-websocket-protocol", "")
    if not raw_header:
        return ""
    for protocol in raw_header.split(","):
        protocol = protocol.strip()
        if protocol:
            return protocol
    return ""


@router.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time notification push.

    Authenticate via Sec-WebSocket-Protocol header.
    """
    token = _extract_ws_token(websocket)
    person_id_str = _authenticate_ws(token)
    if not person_id_str:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    from uuid import UUID

    person_id = UUID(person_id_str)
    await ws_manager.connect(person_id, websocket, subprotocol=token)
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(person_id, websocket)
    except Exception:
        ws_manager.disconnect(person_id, websocket)
