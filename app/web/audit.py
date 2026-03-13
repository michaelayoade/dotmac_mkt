"""Admin web routes for Audit Event viewing (read-only)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.audit import AuditActorType, AuditEvent
from app.services.audit import audit_events
from app.services.branding_context import load_branding_context
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/audit", tags=["web-audit"])

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
def list_audit_events(
    request: Request,
    page: int = 1,
    action: str | None = None,
    entity_type: str | None = None,
    actor_type: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List audit events with pagination and filtering."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE

    query = (
        select(AuditEvent)
        .where(AuditEvent.is_active.is_(True))
        .order_by(AuditEvent.occurred_at.desc())
    )

    if action:
        query = query.where(AuditEvent.action == action)
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if actor_type:
        try:
            parsed_actor_type = AuditActorType(actor_type)
            query = query.where(AuditEvent.actor_type == parsed_actor_type)
        except ValueError:
            pass  # Ignore invalid actor_type filter

    total = (
        db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        or 0
    )
    items = list(db.scalars(query.limit(PAGE_SIZE).offset(offset)).all())
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # Collect distinct values for filter dropdowns
    actor_types = [at.value for at in AuditActorType]

    ctx = _base_context(request, db, auth, title="Audit Log", page_title="Audit Log")
    ctx.update(
        {
            "events": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "action_filter": action or "",
            "entity_type_filter": entity_type or "",
            "actor_type_filter": actor_type or "",
            "actor_types": actor_types,
        }
    )
    return templates.TemplateResponse("admin/audit/list.html", ctx)


@router.get("/{event_id}", response_class=HTMLResponse)
def audit_event_detail(
    request: Request,
    event_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Show audit event detail view."""
    event = audit_events.get(db, str(event_id))
    ctx = _base_context(
        request, db, auth, title="Audit Event Detail", page_title="Audit Event Detail"
    )
    ctx["event"] = event
    return templates.TemplateResponse("admin/audit/detail.html", ctx)
