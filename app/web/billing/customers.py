"""Admin web routes for Customer management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.billing import CustomerCreate, CustomerUpdate
from app.services import billing as billing_service
from app.services.branding_context import load_branding_context
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/billing/customers", tags=["web-billing-customers"])

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
def list_customers(
    request: Request,
    page: int = 1,
    email: str | None = None,
    is_active: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List customers with pagination and optional email search."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    active_filter: bool | None = None
    if is_active == "true":
        active_filter = True
    elif is_active == "false":
        active_filter = False
    items, total = billing_service.customers.list(
        db,
        person_id=None,
        email=email,
        is_active=active_filter,
        order_by="created_at",
        order_dir="desc",
        limit=PAGE_SIZE,
        offset=offset,
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    ctx = _base_context(request, db, auth, title="Customers", page_title="Customers")
    ctx.update(
        {
            "customers": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "email_filter": email or "",
            "is_active_filter": is_active or "",
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/billing/customers/list.html", ctx)


@router.get("/create", response_class=HTMLResponse)
def create_customer_form(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the create customer form."""
    ctx = _base_context(
        request, db, auth, title="Create Customer", page_title="Create Customer"
    )
    return templates.TemplateResponse("admin/billing/customers/create.html", ctx)


@router.post("/create", response_model=None)
async def create_customer_submit(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle customer creation form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        payload = CustomerCreate(
            name=str(data.get("name", "")),
            email=str(data.get("email", "")),
            currency=str(data.get("currency", "usd")),
            balance=int(data["balance"]) if data.get("balance") else 0,
            tax_id=str(data["tax_id"]) if data.get("tax_id") else None,
            external_id=str(data["external_id"]) if data.get("external_id") else None,
            is_active=data.get("is_active") == "on",
        )
        billing_service.customers.create(db, payload)
        logger.info("Created customer via web: %s", payload.email)
        return RedirectResponse(
            url="/admin/billing/customers?success=Customer+created+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to create customer: %s", exc)
        ctx = _base_context(
            request, db, auth, title="Create Customer", page_title="Create Customer"
        )
        ctx["error"] = str(exc)
        ctx["form_data"] = data
        return templates.TemplateResponse("admin/billing/customers/create.html", ctx)


@router.get("/{item_id}", response_class=HTMLResponse)
def customer_detail(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Show customer detail view with subscriptions and payment methods."""
    item = billing_service.customers.get(db, str(item_id))
    ctx = _base_context(
        request, db, auth, title=item.name, page_title="Customer Detail"
    )
    ctx["customer"] = item
    # Load related subscriptions
    subs, _ = billing_service.subscriptions.list(
        db,
        customer_id=str(item_id),
        status=None,
        is_active=None,
        order_by="created_at",
        order_dir="desc",
        limit=50,
        offset=0,
    )
    ctx["subscriptions"] = subs
    # Load related payment methods
    pms, _ = billing_service.payment_methods.list(
        db,
        customer_id=str(item_id),
        type=None,
        is_active=None,
        order_by="created_at",
        order_dir="desc",
        limit=50,
        offset=0,
    )
    ctx["payment_methods"] = pms
    ctx["success"] = request.query_params.get("success")
    ctx["error"] = request.query_params.get("error")
    return templates.TemplateResponse("admin/billing/customers/detail.html", ctx)


@router.get("/{item_id}/edit", response_class=HTMLResponse)
def edit_customer_form(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the edit customer form."""
    item = billing_service.customers.get(db, str(item_id))
    ctx = _base_context(
        request, db, auth, title="Edit Customer", page_title="Edit Customer"
    )
    ctx["customer"] = item
    return templates.TemplateResponse("admin/billing/customers/edit.html", ctx)


@router.post("/{item_id}/edit", response_model=None)
async def edit_customer_submit(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle customer edit form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        payload = CustomerUpdate(
            name=str(data["name"]) if data.get("name") else None,
            email=str(data["email"]) if data.get("email") else None,
            currency=str(data["currency"]) if data.get("currency") else None,
            balance=int(data["balance"]) if data.get("balance") else None,
            tax_id=str(data["tax_id"]) if data.get("tax_id") else None,
            external_id=str(data["external_id"]) if data.get("external_id") else None,
            is_active="is_active" in data,
        )
        billing_service.customers.update(db, str(item_id), payload)
        logger.info("Updated customer via web: %s", item_id)
        return RedirectResponse(
            url=f"/admin/billing/customers/{item_id}?success=Customer+updated+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to update customer %s: %s", item_id, exc)
        item = billing_service.customers.get(db, str(item_id))
        ctx = _base_context(
            request, db, auth, title="Edit Customer", page_title="Edit Customer"
        )
        ctx["customer"] = item
        ctx["error"] = str(exc)
        return templates.TemplateResponse("admin/billing/customers/edit.html", ctx)


@router.post("/{item_id}/delete", response_model=None)
async def delete_customer(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle customer deletion."""
    form = await request.form()
    _ = form.get("csrf_token")  # consumed for CSRF validation

    try:
        billing_service.customers.delete(db, str(item_id))
        logger.info("Deleted customer via web: %s", item_id)
        return RedirectResponse(
            url="/admin/billing/customers?success=Customer+deleted+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to delete customer %s: %s", item_id, exc)
        return RedirectResponse(
            url=f"/admin/billing/customers?error={exc}",
            status_code=302,
        )
