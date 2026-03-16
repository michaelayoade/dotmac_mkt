"""Asset library web routes."""

from __future__ import annotations

import contextlib
import logging
import math
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.deps import get_db
from app.models.asset import AssetType
from app.schemas.asset import AssetCreate, AssetUpdate
from app.services.asset_service import AssetService
from app.services.campaign_service import CampaignService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["web-assets"])

PAGE_SIZE = 25


@router.get("", response_class=HTMLResponse)
def list_assets(
    request: Request,
    page: int = 1,
    asset_type: str | None = None,
    campaign_id: UUID | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Asset library with grid/list view, filters, and search."""
    # Resolve asset_type filter
    type_filter: AssetType | None = None
    if asset_type:
        with contextlib.suppress(ValueError):
            type_filter = AssetType(asset_type)

    # Use service for filtered + paginated listing
    # Search by name requires direct query
    from sqlalchemy import func, select

    from app.models.asset import Asset, DriveStatus
    from app.models.campaign import campaign_assets

    stmt = select(Asset).where(Asset.drive_status != DriveStatus.missing)
    if type_filter is not None:
        stmt = stmt.where(Asset.asset_type == type_filter)
    if campaign_id is not None:
        stmt = stmt.join(campaign_assets, Asset.id == campaign_assets.c.asset_id).where(
            campaign_assets.c.campaign_id == campaign_id
        )
    if q:
        stmt = stmt.where(Asset.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Asset.created_at.desc())

    # Count for pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    offset = (page - 1) * PAGE_SIZE
    items = list(db.scalars(stmt.offset(offset).limit(PAGE_SIZE)).all())

    # Campaigns for filter dropdown
    campaign_svc = CampaignService(db)
    campaigns = campaign_svc.list_all(limit=100)

    ctx = {
        "request": request,
        "title": "Assets",
        "assets": items,
        "campaigns": campaigns,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "asset_type_filter": asset_type if asset_type else "",
        "campaign_id_filter": str(campaign_id) if campaign_id else "",
        "search_query": q if q else "",
        "asset_types": [t.value for t in AssetType],
    }
    return templates.TemplateResponse("assets/list.html", ctx)


@router.get("/create", response_class=HTMLResponse)
def create_asset_form(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render asset upload/create form."""
    campaign_svc = CampaignService(db)
    campaigns = campaign_svc.list_all(limit=100)

    ctx = {
        "request": request,
        "title": "Add Asset",
        "mode": "create",
        "asset_types": [t.value for t in AssetType],
        "campaigns": campaigns,
    }
    return templates.TemplateResponse("assets/form.html", ctx)


@router.post("/create", response_model=None)
async def create_asset_submit(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle asset creation form submission."""
    form = await request.form()
    data = AssetCreate(
        name=str(form.get("name", "")),
        asset_type=AssetType(str(form.get("asset_type", "document"))),
        drive_file_id=str(form.get("drive_file_id", "")) or None,
        drive_url=str(form.get("drive_url", "")) or None,
        thumbnail_url=str(form.get("thumbnail_url", "")) or None,
        mime_type=str(form.get("mime_type", "")) or None,
    )

    asset_svc = AssetService(db)
    record = asset_svc.create(data, uploaded_by=UUID(auth["person_id"]))
    db.commit()
    logger.info("Asset created via web: %s", record.id)
    return RedirectResponse(url=f"/assets/{record.id}", status_code=302)


@router.get("/{id}", response_class=HTMLResponse)
def asset_detail(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Asset detail page with preview, metadata, and linked campaigns."""
    asset_svc = AssetService(db)
    record = asset_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/assets?error=Asset+not+found", status_code=302)

    ctx = {
        "request": request,
        "title": record.name,
        "asset": record,
        "campaigns": record.campaigns,
    }
    return templates.TemplateResponse("assets/detail.html", ctx)


@router.get("/{id}/edit", response_class=HTMLResponse)
def edit_asset_form(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Render asset edit form."""
    asset_svc = AssetService(db)
    record = asset_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/assets?error=Asset+not+found", status_code=302)
    if record.uploaded_by and record.uploaded_by != UUID(auth["person_id"]):
        return RedirectResponse(url="/assets?error=Permission+denied", status_code=302)

    ctx = {
        "request": request,
        "title": f"Edit {record.name}",
        "mode": "edit",
        "asset": record,
        "asset_types": [t.value for t in AssetType],
    }
    return templates.TemplateResponse("assets/form.html", ctx)


@router.post("/{id}/edit", response_model=None)
async def edit_asset_submit(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle asset edit form submission."""
    asset_svc_check = AssetService(db)
    record_check = asset_svc_check.get_by_id(id)
    if record_check is None:
        return RedirectResponse(url="/assets?error=Asset+not+found", status_code=302)
    if record_check.uploaded_by and record_check.uploaded_by != UUID(auth["person_id"]):
        return RedirectResponse(url="/assets?error=Permission+denied", status_code=302)

    form = await request.form()
    data = AssetUpdate(
        name=str(form.get("name", "")) or None,
        asset_type=AssetType(str(form.get("asset_type", "")))
        if form.get("asset_type")
        else None,
        drive_url=str(form.get("drive_url", "")) or None,
        thumbnail_url=str(form.get("thumbnail_url", "")) or None,
        mime_type=str(form.get("mime_type", "")) or None,
    )

    asset_svc = AssetService(db)
    try:
        asset_svc.update(id, data)
        db.commit()
        logger.info("Asset updated via web: %s", id)
    except ValueError:
        return RedirectResponse(url="/assets?error=Asset+not+found", status_code=302)

    return RedirectResponse(url=f"/assets/{id}", status_code=302)


@router.post("/{id}/delete", response_model=None)
def delete_asset(
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Delete an asset."""
    asset_svc = AssetService(db)
    record = asset_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/assets?error=Asset+not+found", status_code=302)
    if record.uploaded_by and record.uploaded_by != UUID(auth["person_id"]):
        return RedirectResponse(url="/assets?error=Permission+denied", status_code=302)
    try:
        asset_svc.delete(id)
        db.commit()
        logger.info("Asset deleted via web: %s", id)
    except ValueError:
        return RedirectResponse(url="/assets?error=Asset+not+found", status_code=302)
    return RedirectResponse(url="/assets?success=Asset+deleted", status_code=302)
