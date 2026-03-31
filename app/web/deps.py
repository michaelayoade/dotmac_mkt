"""Web authentication dependencies — cookie-based JWT auth."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.auth import Session as AuthSession
from app.models.auth import SessionStatus
from app.models.person import Person
from app.services.auth_flow import AuthFlow, decode_access_token
from app.services.common import coerce_uuid

logger = logging.getLogger(__name__)


class WebAuthRedirect(HTTPException):
    """Raised when web auth fails — triggers redirect to login page."""

    def __init__(self, next_url: str = "/admin") -> None:
        self.next_url = next_url
        super().__init__(status_code=302, detail="Not authenticated")


def _make_aware(dt: datetime) -> datetime:
    if dt is None:
        return None  # type: ignore[return-value]
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _is_secure_request(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "")
    return proto == "https" or request.url.scheme == "https"


def _set_cookie_and_queue(
    request: Request,
    response: Response,
    *,
    key: str,
    value: str,
    httponly: bool,
    secure: bool,
    samesite: str,
    path: str,
    max_age: int,
    domain: str | None = None,
) -> None:
    cookie_kwargs = {
        "key": key,
        "value": value,
        "httponly": httponly,
        "secure": secure,
        "samesite": samesite,
        "path": path,
        "max_age": max_age,
        "domain": domain,
    }
    response.set_cookie(**cookie_kwargs)
    queued = getattr(request.state, "auth_cookies_to_set", [])
    queued.append(cookie_kwargs)
    request.state.auth_cookies_to_set = queued


def _refresh_web_tokens(request: Request, response: Response, db: Session) -> dict:
    refresh_token = AuthFlow.resolve_refresh_token(request, None, db)
    if not refresh_token:
        raise WebAuthRedirect(next_url=request.url.path)

    try:
        refreshed = AuthFlow.refresh(db, refresh_token, request)
    except HTTPException:
        raise WebAuthRedirect(next_url=request.url.path)

    access_token = refreshed.get("access_token", "")
    new_refresh_token = refreshed.get("refresh_token", "")
    if not access_token or not new_refresh_token:
        raise WebAuthRedirect(next_url=request.url.path)

    secure = _is_secure_request(request)
    _set_cookie_and_queue(
        request,
        response,
        key="access_token",
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=3600,
    )
    refresh_settings = AuthFlow.refresh_cookie_settings(db)
    _set_cookie_and_queue(
        request,
        response,
        key=refresh_settings["key"],
        value=new_refresh_token,
        httponly=bool(refresh_settings["httponly"]),
        secure=bool(refresh_settings["secure"]),
        samesite=str(refresh_settings["samesite"]),
        path=str(refresh_settings["path"]),
        domain=refresh_settings["domain"],
        max_age=int(refresh_settings["max_age"]),
    )
    return decode_access_token(db, access_token)


def require_web_auth(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    """Read JWT from access_token cookie and validate session.

    Returns dict with person_id, session_id, roles, person.
    Raises WebAuthRedirect on failure.
    """
    token = request.cookies.get("access_token", "")
    if not token:
        payload = _refresh_web_tokens(request, response, db)
    else:
        try:
            payload = decode_access_token(db, token)
        except HTTPException:
            payload = _refresh_web_tokens(request, response, db)

    person_id = payload.get("sub")
    session_id = payload.get("session_id")
    if not person_id or not session_id:
        raise WebAuthRedirect(next_url=request.url.path)

    now = datetime.now(UTC)
    person_uuid = coerce_uuid(person_id)
    session_uuid = coerce_uuid(session_id)
    session = db.get(AuthSession, session_uuid)
    if (
        not session
        or session.person_id != person_uuid
        or session.status != SessionStatus.active
        or session.revoked_at is not None
        or _make_aware(session.expires_at) <= now
    ):
        raise WebAuthRedirect(next_url=request.url.path)

    person = db.get(Person, person_uuid)
    if not person:
        raise WebAuthRedirect(next_url=request.url.path)

    raw_roles = payload.get("roles", [])
    roles = [str(r) for r in raw_roles] if isinstance(raw_roles, list) else []

    return {
        "person_id": str(person_id),
        "session_id": str(session_id),
        "roles": roles,
        "person": person,
    }
