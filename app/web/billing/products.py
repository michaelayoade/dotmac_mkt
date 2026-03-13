"""Admin web routes for Product management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.billing import ProductCreate, ProductUpdate
from app.services import billing as billing_service
from app.services.branding_context import load_branding_context
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/billing/products", tags=["web-billing-products"])

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
def list_products(
    request: Request,
    page: int = 1,
    is_active: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List products with pagination and optional is_active filter."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    active_filter: bool | None = None
    if is_active == "true":
        active_filter = True
    elif is_active == "false":
        active_filter = False
    items, total = billing_service.products.list(
        db,
        is_active=active_filter,
        order_by="created_at",
        order_dir="desc",
        limit=PAGE_SIZE,
        offset=offset,
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    ctx = _base_context(request, db, auth, title="Products", page_title="Products")
    ctx.update(
        {
            "products": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "is_active_filter": is_active or "",
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/billing/products/list.html", ctx)


@router.get("/create", response_class=HTMLResponse)
def create_product_form(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the create product form."""
    ctx = _base_context(
        request, db, auth, title="Create Product", page_title="Create Product"
    )
    return templates.TemplateResponse("admin/billing/products/create.html", ctx)


@router.post("/create", response_model=None)
async def create_product_submit(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle product creation form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        payload = ProductCreate(
            name=str(data.get("name", "")),
            description=str(data["description"]) if data.get("description") else None,
            is_active=data.get("is_active") == "on",
        )
        billing_service.products.create(db, payload)
        logger.info("Created product via web: %s", payload.name)
        return RedirectResponse(
            url="/admin/billing/products?success=Product+created+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to create product: %s", exc)
        ctx = _base_context(
            request, db, auth, title="Create Product", page_title="Create Product"
        )
        ctx["error"] = str(exc)
        ctx["form_data"] = data
        return templates.TemplateResponse("admin/billing/products/create.html", ctx)


@router.get("/{item_id}", response_class=HTMLResponse)
def product_detail(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Show product detail view."""
    item = billing_service.products.get(db, str(item_id))
    ctx = _base_context(request, db, auth, title=item.name, page_title="Product Detail")
    ctx["product"] = item
    # Load related prices
    prices, _ = billing_service.prices.list(
        db,
        product_id=str(item_id),
        type=None,
        currency=None,
        is_active=None,
        order_by="created_at",
        order_dir="desc",
        limit=50,
        offset=0,
    )
    ctx["prices"] = prices
    ctx["success"] = request.query_params.get("success")
    ctx["error"] = request.query_params.get("error")
    return templates.TemplateResponse("admin/billing/products/detail.html", ctx)


@router.get("/{item_id}/edit", response_class=HTMLResponse)
def edit_product_form(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the edit product form."""
    item = billing_service.products.get(db, str(item_id))
    ctx = _base_context(
        request, db, auth, title="Edit Product", page_title="Edit Product"
    )
    ctx["product"] = item
    return templates.TemplateResponse("admin/billing/products/edit.html", ctx)


@router.post("/{item_id}/edit", response_model=None)
async def edit_product_submit(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle product edit form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        payload = ProductUpdate(
            name=str(data["name"]) if data.get("name") else None,
            description=str(data["description"]) if data.get("description") else None,
            is_active="is_active" in data,
        )
        billing_service.products.update(db, str(item_id), payload)
        logger.info("Updated product via web: %s", item_id)
        return RedirectResponse(
            url=f"/admin/billing/products/{item_id}?success=Product+updated+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to update product %s: %s", item_id, exc)
        item = billing_service.products.get(db, str(item_id))
        ctx = _base_context(
            request, db, auth, title="Edit Product", page_title="Edit Product"
        )
        ctx["product"] = item
        ctx["error"] = str(exc)
        return templates.TemplateResponse("admin/billing/products/edit.html", ctx)


@router.post("/{item_id}/delete", response_model=None)
async def delete_product(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle product deletion."""
    form = await request.form()
    _ = form.get("csrf_token")  # consumed for CSRF validation

    try:
        billing_service.products.delete(db, str(item_id))
        logger.info("Deleted product via web: %s", item_id)
        return RedirectResponse(
            url="/admin/billing/products?success=Product+deleted+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to delete product %s: %s", item_id, exc)
        return RedirectResponse(
            url=f"/admin/billing/products?error={exc}",
            status_code=302,
        )
