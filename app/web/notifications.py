"""Admin web routes for Notification management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.notification import Notification
from app.services.branding_context import load_branding_context
from app.services.notification import NotificationService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/notifications", tags=["web-notifications"])

PAGE_SIZE = 25


def _base_context(
    request: Request,
    db: Session,
    auth: dict,
    *,
    title: str,
    page_title: str,
) -> dict:
    branding = load_branding_context(db)
    person = auth["person"]
    return {
        "request": request,
        "title": title,
        "page_title": page_title,
        "current_user": person,
        "brand": branding["brand"],
        "org_branding": branding["org_branding"],
        "brand_mark": branding["brand"].get("mark", "A"),
    }


@router.get("", response_class=HTMLResponse)
def list_notifications(
    request: Request,
    page: int = 1,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List notifications for the current user with pagination."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    person = auth["person"]

    query = (
        select(Notification)
        .where(
            Notification.recipient_id == person.id,
            Notification.is_active.is_(True),
        )
        .order_by(Notification.created_at.desc())
    )
    total = (
        db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        or 0
    )
    items = list(db.scalars(query.limit(PAGE_SIZE).offset(offset)).all())
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # Count unread
    svc = NotificationService(db)
    unread_count = svc.unread_count(person.id)

    ctx = _base_context(
        request, db, auth, title="Notifications", page_title="Notifications"
    )
    ctx.update(
        {
            "notifications": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "unread_count": unread_count,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/notifications/list.html", ctx)


@router.post("/{notification_id}/read", response_model=None)
async def mark_notification_read(
    request: Request,
    notification_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Mark a notification as read."""
    form = await request.form()
    _ = form.get("csrf_token")

    person = auth["person"]
    svc = NotificationService(db)

    try:
        result = svc.mark_read(notification_id, person.id)
        if result:
            db.commit()
            logger.info(
                "Marked notification %s as read for user %s",
                notification_id,
                person.id,
            )
            return RedirectResponse(
                url="/admin/notifications?success=Notification+marked+as+read",
                status_code=302,
            )
        else:
            return RedirectResponse(
                url="/admin/notifications?error=Notification+not+found",
                status_code=302,
            )
    except Exception as exc:
        logger.warning(
            "Failed to mark notification %s as read: %s", notification_id, exc
        )
        return RedirectResponse(
            url=f"/admin/notifications?error={exc}",
            status_code=302,
        )
