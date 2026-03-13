"""Admin web routes for Subscription management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.billing import SubscriptionUpdate
from app.services import billing as billing_service
from app.services.branding_context import load_branding_context
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/billing/subscriptions", tags=["web-billing-subscriptions"]
)

PAGE_SIZE = 25

SUBSCRIPTION_STATUSES = [
    "incomplete",
    "trialing",
    "active",
    "past_due",
    "canceled",
    "unpaid",
    "paused",
]


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
def list_subscriptions(
    request: Request,
    page: int = 1,
    customer_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List subscriptions with pagination and optional filters."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    items, total = billing_service.subscriptions.list(
        db,
        customer_id=customer_id,
        status=status,
        is_active=None,
        order_by="created_at",
        order_dir="desc",
        limit=PAGE_SIZE,
        offset=offset,
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    # Load customers for filter display
    all_customers, _ = billing_service.customers.list(
        db,
        person_id=None,
        email=None,
        is_active=None,
        order_by="name",
        order_dir="asc",
        limit=500,
        offset=0,
    )
    ctx = _base_context(
        request, db, auth, title="Subscriptions", page_title="Subscriptions"
    )
    ctx.update(
        {
            "subscriptions": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "customers": all_customers,
            "customer_id_filter": customer_id or "",
            "status_filter": status or "",
            "statuses": SUBSCRIPTION_STATUSES,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/billing/subscriptions/list.html", ctx)


@router.get("/{item_id}", response_class=HTMLResponse)
def subscription_detail(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Show subscription detail view with items and invoices."""
    item = billing_service.subscriptions.get(db, str(item_id))
    customer = billing_service.customers.get(db, str(item.customer_id))
    ctx = _base_context(
        request,
        db,
        auth,
        title=f"Subscription - {customer.name}",
        page_title="Subscription Detail",
    )
    ctx["subscription"] = item
    ctx["customer"] = customer
    # Load subscription items
    sub_items, _ = billing_service.subscription_items.list(
        db,
        subscription_id=str(item_id),
        price_id=None,
        order_by="created_at",
        order_dir="desc",
        limit=50,
        offset=0,
    )
    ctx["subscription_items"] = sub_items
    # Load related invoices
    invoices, _ = billing_service.invoices.list(
        db,
        customer_id=None,
        subscription_id=str(item_id),
        status=None,
        order_by="created_at",
        order_dir="desc",
        limit=50,
        offset=0,
    )
    ctx["invoices"] = invoices
    ctx["statuses"] = SUBSCRIPTION_STATUSES
    ctx["success"] = request.query_params.get("success")
    ctx["error"] = request.query_params.get("error")
    return templates.TemplateResponse("admin/billing/subscriptions/detail.html", ctx)


@router.get("/{item_id}/edit", response_class=HTMLResponse)
def edit_subscription_form(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the edit subscription form."""
    item = billing_service.subscriptions.get(db, str(item_id))
    customer = billing_service.customers.get(db, str(item.customer_id))
    ctx = _base_context(
        request, db, auth, title="Edit Subscription", page_title="Edit Subscription"
    )
    ctx["subscription"] = item
    ctx["customer"] = customer
    ctx["statuses"] = SUBSCRIPTION_STATUSES
    return templates.TemplateResponse("admin/billing/subscriptions/edit.html", ctx)


@router.post("/{item_id}/edit", response_model=None)
async def edit_subscription_submit(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle subscription edit form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        payload = SubscriptionUpdate(
            status=str(data["status"]) if data.get("status") else None,  # type: ignore[arg-type]
            cancel_at_period_end="cancel_at_period_end" in data,
            external_id=str(data["external_id"]) if data.get("external_id") else None,
            is_active="is_active" in data,
        )
        billing_service.subscriptions.update(db, str(item_id), payload)
        logger.info("Updated subscription via web: %s", item_id)
        return RedirectResponse(
            url=f"/admin/billing/subscriptions/{item_id}?success=Subscription+updated+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to update subscription %s: %s", item_id, exc)
        item = billing_service.subscriptions.get(db, str(item_id))
        customer = billing_service.customers.get(db, str(item.customer_id))
        ctx = _base_context(
            request,
            db,
            auth,
            title="Edit Subscription",
            page_title="Edit Subscription",
        )
        ctx["subscription"] = item
        ctx["customer"] = customer
        ctx["statuses"] = SUBSCRIPTION_STATUSES
        ctx["error"] = str(exc)
        return templates.TemplateResponse("admin/billing/subscriptions/edit.html", ctx)


@router.post("/{item_id}/delete", response_model=None)
async def delete_subscription(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle subscription deletion."""
    form = await request.form()
    _ = form.get("csrf_token")  # consumed for CSRF validation

    try:
        billing_service.subscriptions.delete(db, str(item_id))
        logger.info("Deleted subscription via web: %s", item_id)
        return RedirectResponse(
            url="/admin/billing/subscriptions?success=Subscription+deleted+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to delete subscription %s: %s", item_id, exc)
        return RedirectResponse(
            url=f"/admin/billing/subscriptions?error={exc}",
            status_code=302,
        )
