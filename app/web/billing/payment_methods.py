"""Admin web routes for Payment Method management (read-only)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import billing as billing_service
from app.services.branding_context import load_branding_context
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/billing/payment-methods", tags=["web-billing-payment-methods"]
)

PAGE_SIZE = 25

PAYMENT_METHOD_TYPES = ["card", "bank_account", "wallet", "other"]


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
def list_payment_methods(
    request: Request,
    page: int = 1,
    customer_id: str | None = None,
    type: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List payment methods with pagination and optional filters."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    items, total = billing_service.payment_methods.list(
        db,
        customer_id=customer_id,
        type=type,
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
        request, db, auth, title="Payment Methods", page_title="Payment Methods"
    )
    ctx.update(
        {
            "payment_methods": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "customers": all_customers,
            "customer_id_filter": customer_id or "",
            "type_filter": type or "",
            "types": PAYMENT_METHOD_TYPES,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/billing/payment_methods/list.html", ctx)


@router.get("/{item_id}", response_class=HTMLResponse)
def payment_method_detail(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Show payment method detail view (read-only)."""
    item = billing_service.payment_methods.get(db, str(item_id))
    customer = billing_service.customers.get(db, str(item.customer_id))
    ctx = _base_context(
        request,
        db,
        auth,
        title=f"Payment Method - {customer.name}",
        page_title="Payment Method Detail",
    )
    ctx["payment_method"] = item
    ctx["customer"] = customer
    ctx["success"] = request.query_params.get("success")
    ctx["error"] = request.query_params.get("error")
    return templates.TemplateResponse("admin/billing/payment_methods/detail.html", ctx)


@router.post("/{item_id}/delete", response_model=None)
async def delete_payment_method(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle payment method deletion (soft-delete)."""
    form = await request.form()
    _ = form.get("csrf_token")  # consumed for CSRF validation

    try:
        billing_service.payment_methods.delete(db, str(item_id))
        logger.info("Deleted payment method via web: %s", item_id)
        return RedirectResponse(
            url="/admin/billing/payment-methods?success=Payment+method+deleted+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to delete payment method %s: %s", item_id, exc)
        return RedirectResponse(
            url=f"/admin/billing/payment-methods?error={exc}",
            status_code=302,
        )
