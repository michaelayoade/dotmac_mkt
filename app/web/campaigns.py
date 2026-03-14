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
from app.models.campaign import Campaign, CampaignStatus, campaign_members
from app.models.post import Post, PostStatus
from app.models.task import Task
from app.schemas.campaign import CampaignCreate, CampaignUpdate
from app.services.asset_service import AssetService
from app.services.campaign_service import CampaignService
from app.services.post_service import PostService
from app.services.task_service import MktTaskService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["web-campaigns"])

PAGE_SIZE = 25


def _can_edit_campaign(db: Session, campaign: Campaign, person_id: UUID) -> bool:
    """Check if a person is the creator or a member of the campaign."""
    if campaign.created_by == person_id:
        return True
    member = db.execute(
        select(campaign_members.c.person_id)
        .where(campaign_members.c.campaign_id == campaign.id)
        .where(campaign_members.c.person_id == person_id)
    ).first()
    return member is not None


@router.get("", response_class=HTMLResponse)
def list_campaigns(
    request: Request,
    page: int = 1,
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List campaigns with optional status filter and name search."""
    from sqlalchemy import func

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
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    offset = (page - 1) * PAGE_SIZE
    items = list(db.scalars(stmt.offset(offset).limit(PAGE_SIZE)).all())

    # Batch fetch post/task counts in two queries instead of 2*N
    if items:
        campaign_ids = [c.id for c in items]

        post_counts = dict(
            db.execute(
                select(Post.campaign_id, func.count(Post.id))
                .where(Post.campaign_id.in_(campaign_ids))
                .group_by(Post.campaign_id)
            ).all()
        )
        task_counts = dict(
            db.execute(
                select(Task.campaign_id, func.count(Task.id))
                .where(Task.campaign_id.in_(campaign_ids))
                .group_by(Task.campaign_id)
            ).all()
        )

        for c in items:
            c.posts_count = post_counts.get(c.id, 0)
            c.tasks_count = task_counts.get(c.id, 0)

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
    auth: dict = Depends(require_web_auth),
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
    auth: dict = Depends(require_web_auth),
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
    record = campaign_svc.create(data, created_by=UUID(auth["person_id"]))
    db.commit()
    logger.info("Campaign created via web: %s", record.id)
    return RedirectResponse(url=f"/campaigns/{record.id}", status_code=302)


@router.get("/{id}", response_class=HTMLResponse)
def campaign_detail(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Campaign detail page with posts, tasks, and assets tabs."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/campaigns?error=Campaign+not+found", status_code=302)

    post_svc = PostService(db)
    all_posts = post_svc.list_all(campaign_id=id)
    total_posts = len(all_posts)
    published_posts = sum(1 for p in all_posts if p.status == PostStatus.published)
    progress_pct = round(published_posts / total_posts * 100) if total_posts > 0 else 0

    ctx = {
        "request": request,
        "title": record.name,
        "campaign": record,
        "total_posts": total_posts,
        "published_posts": published_posts,
        "progress_pct": progress_pct,
    }
    return templates.TemplateResponse("campaigns/detail.html", ctx)


@router.get("/{id}/tab/{tab}", response_class=HTMLResponse)
def campaign_tab(
    request: Request,
    id: UUID,
    tab: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Lazy-load a campaign detail tab via HTMX."""
    allowed_tabs = {"posts", "assets", "tasks", "analytics"}
    if tab not in allowed_tabs:
        return HTMLResponse(content="", status_code=404)

    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return HTMLResponse(content="<p class='text-sm text-red-500'>Campaign not found</p>", status_code=404)

    ctx: dict = {"request": request, "campaign": record}

    if tab == "posts":
        post_svc = PostService(db)
        ctx["posts"] = post_svc.list_all(campaign_id=id)
        return templates.TemplateResponse("campaigns/tabs/posts.html", ctx)
    elif tab == "assets":
        asset_svc = AssetService(db)
        ctx["assets"] = asset_svc.list_all(campaign_id=id)
        return templates.TemplateResponse("campaigns/tabs/assets.html", ctx)
    elif tab == "tasks":
        task_svc = MktTaskService(db)
        ctx["tasks"] = task_svc.list_all(campaign_id=id)
        return templates.TemplateResponse("campaigns/tabs/tasks.html", ctx)
    elif tab == "analytics":
        return templates.TemplateResponse("campaigns/tabs/analytics.html", ctx)
    else:
        return HTMLResponse(content="", status_code=404)


@router.get("/{id}/edit", response_class=HTMLResponse)
def edit_campaign_form(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Render campaign edit form."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/campaigns?error=Campaign+not+found", status_code=302)
    if not _can_edit_campaign(db, record, UUID(auth["person_id"])):
        return RedirectResponse(url="/campaigns?error=Permission+denied", status_code=302)

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
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle campaign edit form submission."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/campaigns?error=Campaign+not+found", status_code=302)
    if not _can_edit_campaign(db, record, UUID(auth["person_id"])):
        return RedirectResponse(url="/campaigns?error=Permission+denied", status_code=302)

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
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Archive a campaign."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(url="/campaigns?error=Campaign+not+found", status_code=302)
    if not _can_edit_campaign(db, record, UUID(auth["person_id"])):
        return RedirectResponse(url="/campaigns?error=Permission+denied", status_code=302)
    try:
        campaign_svc.archive(id)
        db.commit()
        logger.info("Campaign archived via web: %s", id)
    except ValueError:
        pass
    return RedirectResponse(url="/campaigns", status_code=302)
