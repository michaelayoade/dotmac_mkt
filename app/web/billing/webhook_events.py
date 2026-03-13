"""Admin web routes for Webhook Event management (read-only)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import billing as billing_service
from app.services.branding_context import load_branding_context
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/billing/webhook-events", tags=["web-billing-webhook-events"]
)

PAGE_SIZE = 25

WEBHOOK_STATUSES = ["pending", "processed", "failed"]


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
def list_webhook_events(
    request: Request,
    page: int = 1,
    provider: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List webhook events with pagination and optional filters."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    items, total = billing_service.webhook_events.list(
        db,
        provider=provider,
        event_type=None,
        status=status,
        order_by="created_at",
        order_dir="desc",
        limit=PAGE_SIZE,
        offset=offset,
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    ctx = _base_context(
        request, db, auth, title="Webhook Events", page_title="Webhook Events"
    )
    ctx.update(
        {
            "webhook_events": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "provider_filter": provider or "",
            "status_filter": status or "",
            "statuses": WEBHOOK_STATUSES,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/billing/webhook_events/list.html", ctx)


@router.get("/{item_id}", response_class=HTMLResponse)
def webhook_event_detail(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Show webhook event detail view (read-only)."""
    item = billing_service.webhook_events.get(db, str(item_id))
    ctx = _base_context(
        request,
        db,
        auth,
        title=f"Webhook Event - {item.event_type}",
        page_title="Webhook Event Detail",
    )
    ctx["event"] = item
    return templates.TemplateResponse("admin/billing/webhook_events/detail.html", ctx)
