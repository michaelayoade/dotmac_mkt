"""Campaign management web routes."""

from __future__ import annotations

import contextlib
import logging
import math
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.deps import get_db
from app.models.campaign import Campaign, CampaignStatus
from app.schemas.campaign import CampaignCreate, CampaignUpdate
from app.services.asset_service import AssetService
from app.services.campaign_service import CampaignService
from app.services.post_service import PostService
from app.services.task_service import MktTaskService
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["web-campaigns"])

PAGE_SIZE = 25

# TODO: get from auth context
PLACEHOLDER_USER_ID = UUID("00000000-0000-0000-0000-000000000000")


@router.get("", response_class=HTMLResponse)
def list_campaigns(
    request: Request,
    page: int = 1,
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """List campaigns with optional status filter and name search."""
    CampaignService(db)

    # Resolve status filter
    status_filter: CampaignStatus | None = None
    if status:
        with contextlib.suppress(ValueError):
            status_filter = CampaignStatus(status)

    # Build query for search support
    stmt = select(Campaign)
    if status_filter is not None:
        stmt = stmt.where(Campaign.status == status_filter)
    if q:
        stmt = stmt.where(Campaign.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Campaign.created_at.desc())

    # Count for pagination
    from sqlalchemy import func

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    offset = (page - 1) * PAGE_SIZE
    items = list(db.scalars(stmt.offset(offset).limit(PAGE_SIZE)).all())

    ctx = {
        "request": request,
        "title": "Campaigns",
        "campaigns": items,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "status_filter": status if status else "",
        "search_query": q if q else "",
        "statuses": [s.value for s in CampaignStatus],
    }
    return templates.TemplateResponse("campaigns/list.html", ctx)


@router.get("/create", response_class=HTMLResponse)
def create_campaign_form(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render campaign creation form."""
    ctx = {
        "request": request,
        "title": "Create Campaign",
        "mode": "create",
        "statuses": [s.value for s in CampaignStatus],
    }
    return templates.TemplateResponse("campaigns/form.html", ctx)


@router.post("/create", response_model=None)
async def create_campaign_submit(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Handle campaign creation form submission."""
    form = await request.form()
    data = CampaignCreate(
        name=str(form.get("name", "")),
        description=str(form.get("description", "")) or None,
        status=CampaignStatus(str(form.get("status", "draft"))),
        start_date=str(form.get("start_date", "")) or None,
        end_date=str(form.get("end_date", "")) or None,
    )

    campaign_svc = CampaignService(db)
    # TODO: get from auth context
    record = campaign_svc.create(data, created_by=PLACEHOLDER_USER_ID)
    db.commit()
    logger.info("Campaign created via web: %s", record.id)
    return RedirectResponse(url=f"/campaigns/{record.id}", status_code=302)


@router.get("/{id}", response_class=HTMLResponse)
def campaign_detail(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Campaign detail page with posts, tasks, and assets tabs."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/campaigns?error=Campaign+not+found", status_code=302)

    post_svc = PostService(db)
    task_svc = MktTaskService(db)
    asset_svc = AssetService(db)

    posts = post_svc.list_all(campaign_id=id)
    tasks = task_svc.list_all(campaign_id=id)
    assets = asset_svc.list_all(campaign_id=id)

    ctx = {
        "request": request,
        "title": record.name,
        "campaign": record,
        "posts": posts,
        "tasks": tasks,
        "assets": assets,
    }
    return templates.TemplateResponse("campaigns/detail.html", ctx)


@router.get("/{id}/edit", response_class=HTMLResponse)
def edit_campaign_form(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Render campaign edit form."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/campaigns?error=Campaign+not+found", status_code=302)

    ctx = {
        "request": request,
        "title": f"Edit {record.name}",
        "mode": "edit",
        "campaign": record,
        "statuses": [s.value for s in CampaignStatus],
    }
    return templates.TemplateResponse("campaigns/form.html", ctx)


@router.post("/{id}/edit", response_model=None)
async def edit_campaign_submit(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Handle campaign edit form submission."""
    form = await request.form()
    data = CampaignUpdate(
        name=str(form.get("name", "")) or None,
        description=str(form.get("description", "")) or None,
        status=CampaignStatus(str(form.get("status", ""))) if form.get("status") else None,
        start_date=str(form.get("start_date", "")) or None,
        end_date=str(form.get("end_date", "")) or None,
    )

    campaign_svc = CampaignService(db)
    try:
        campaign_svc.update(id, data)
        db.commit()
        logger.info("Campaign updated via web: %s", id)
    except ValueError:
        return RedirectResponse(url="/campaigns?error=Campaign+not+found", status_code=302)

    return RedirectResponse(url=f"/campaigns/{id}", status_code=302)


@router.post("/{id}/archive", response_model=None)
def archive_campaign(
    id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Archive a campaign."""
    campaign_svc = CampaignService(db)
    try:
        campaign_svc.archive(id)
        db.commit()
        logger.info("Campaign archived via web: %s", id)
    except ValueError:
        pass
    return RedirectResponse(url="/campaigns", status_code=302)
