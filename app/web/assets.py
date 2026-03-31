"""Asset library web routes."""

from __future__ import annotations

import contextlib
import logging
import math
from urllib.parse import quote_plus
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.deps import get_db
from app.models.asset import AssetType
from app.schemas.asset import AssetCreate, AssetUpdate
from app.services.asset_service import AssetService
from app.services.campaign_service import CampaignService
from app.services.drive_service import DriveService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["web-assets"])

PAGE_SIZE = 25


def _refresh_drive_assets(db: Session) -> None:
    try:
        drive_svc = DriveService(db)
        _, _, folder_id = drive_svc._drive_client_config()
        if not folder_id:
            return
        result = drive_svc.sync_folder()
        if any(result.values()):
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Drive sync refresh failed during assets page render")


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
    _refresh_drive_assets(db)

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
    drive_svc = DriveService(db)
    _, _, default_drive_folder_id = drive_svc._drive_client_config()
    selected_drive_folder_id = (
        request.query_params.get("drive_folder_id", "") or default_drive_folder_id
    )
    selected_drive_folder_name = ""
    try:
        folder = (
            drive_svc.get_folder(folder_id=selected_drive_folder_id)
            if selected_drive_folder_id
            else None
        )
        if folder:
            selected_drive_folder_name = folder["name"]
    except Exception:
        logger.exception(
            "Failed to load selected Drive folder label for asset upload form"
        )

    ctx = {
        "request": request,
        "title": "Add Asset",
        "mode": "create",
        "asset_types": [t.value for t in AssetType],
        "campaigns": campaigns,
        "selected_campaign_id": request.query_params.get("campaign_id", ""),
        "next_url": request.query_params.get("next", ""),
        "error": request.query_params.get("error", ""),
        "selected_drive_folder_id": selected_drive_folder_id,
        "selected_drive_folder_name": selected_drive_folder_name,
        "default_drive_folder_id": default_drive_folder_id,
    }
    return templates.TemplateResponse("assets/form.html", ctx)


@router.get("/drive-folders/search", response_class=JSONResponse)
def search_drive_folders(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=8, ge=1, le=25),
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> JSONResponse:
    try:
        items = DriveService(db).search_folders(query=q.strip(), limit=limit)
    except Exception:
        logger.exception("Drive folder search failed")
        items = []
    return JSONResponse(
        {"items": [{"id": item["id"], "label": item["name"]} for item in items]}
    )


@router.post("/create", response_model=None)
async def create_asset_submit(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle asset creation form submission."""
    form = await request.form()
    uploaded_file: UploadFile | None = form.get("file")  # type: ignore[assignment]
    asset_type = AssetType(str(form.get("asset_type", "document")))
    tags_raw = str(form.get("tags", "")).strip()
    tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]
    drive_folder_id = str(form.get("drive_folder_id", "")).strip() or None
    next_url = str(form.get("next", "")).strip()
    campaign_id_raw = str(form.get("campaign_id", "")).strip()
    campaign_id: UUID | None = None
    if campaign_id_raw:
        with contextlib.suppress(ValueError, TypeError):
            campaign_id = UUID(campaign_id_raw)

    asset_svc = AssetService(db)

    def _final_redirect(asset_id: UUID) -> RedirectResponse:
        if campaign_id is not None:
            asset_svc.link_to_campaign(asset_id, campaign_id)
        db.commit()
        if next_url.startswith("/") and not next_url.startswith("//"):
            return RedirectResponse(url=next_url, status_code=302)
        return RedirectResponse(url=f"/assets/{asset_id}", status_code=302)

    if uploaded_file and uploaded_file.filename:
        drive_svc = DriveService(db)
        try:
            record = drive_svc.upload_asset_file(
                filename=uploaded_file.filename,
                drive_filename=str(form.get("name", "")).strip() or None,
                folder_id=drive_folder_id,
                content_type=uploaded_file.content_type or "application/octet-stream",
                content=await uploaded_file.read(),
                uploaded_by=UUID(auth["person_id"]),
            )
            record.asset_type = asset_type
            record.tags = tags
            logger.info("Asset uploaded to Drive via web: %s", record.id)
            return _final_redirect(record.id)
        except (RuntimeError, ValueError) as exc:
            db.rollback()
            redirect_parts = [f"error={quote_plus(str(exc))}"]
            if campaign_id is not None:
                redirect_parts.append(f"campaign_id={campaign_id}")
            if next_url.startswith("/") and not next_url.startswith("//"):
                redirect_parts.append(f"next={quote_plus(next_url)}")
            return RedirectResponse(
                url="/assets/create?" + "&".join(redirect_parts),
                status_code=302,
            )

    data = AssetCreate(
        name=str(form.get("name", "")),
        asset_type=asset_type,
        drive_file_id=str(form.get("drive_file_id", "")) or None,
        drive_url=str(form.get("drive_url", "")) or None,
        thumbnail_url=str(form.get("thumbnail_url", "")) or None,
        mime_type=str(form.get("mime_type", "")) or None,
        tags=tags,
    )

    record = asset_svc.create(data, uploaded_by=UUID(auth["person_id"]))
    logger.info("Asset created via web: %s", record.id)
    return _final_redirect(record.id)


@router.get("/{id}", response_class=HTMLResponse)
def asset_detail(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Asset detail page with preview, metadata, and linked campaigns."""
    _refresh_drive_assets(db)

    asset_svc = AssetService(db)
    record = asset_svc.get_by_id(id)
    if record is None or getattr(record, "drive_status", None) == "missing":
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
    tags_raw = str(form.get("tags", "")).strip()
    tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]
    data = AssetUpdate(
        name=str(form.get("name", "")) or None,
        asset_type=AssetType(str(form.get("asset_type", "")))
        if form.get("asset_type")
        else None,
        drive_file_id=str(form.get("drive_file_id", "")) or None,
        tags=tags,
    )

    asset_svc = AssetService(db)
    drive_svc = DriveService(db)
    try:
        requested_name = str(form.get("name", "")).strip()
        if requested_name and record_check.drive_file_id:
            drive_svc.rename_asset_file(
                file_id=record_check.drive_file_id,
                display_name=requested_name,
            )
        asset_svc.update(id, data)
        db.commit()
        logger.info("Asset updated via web: %s", id)
    except (RuntimeError, ValueError):
        db.rollback()
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
    drive_svc = DriveService(db)
    record = asset_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/assets?error=Asset+not+found", status_code=302)
    if record.uploaded_by and record.uploaded_by != UUID(auth["person_id"]):
        return RedirectResponse(url="/assets?error=Permission+denied", status_code=302)
    try:
        if record.drive_file_id:
            drive_svc.delete_asset_file(file_id=record.drive_file_id)
        asset_svc.delete(id)
        db.commit()
        logger.info("Asset deleted via web: %s", id)
    except (RuntimeError, ValueError):
        db.rollback()
        return RedirectResponse(url="/assets?error=Asset+not+found", status_code=302)
    return RedirectResponse(url="/assets?success=Asset+deleted", status_code=302)
