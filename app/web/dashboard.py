"""Marketing dashboard — campaign overview, upcoming posts, quick stats."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.asset import Asset
from app.models.campaign import CampaignStatus
from app.models.channel import Channel
from app.models.post import Post
from app.models.task import Task
from app.services.campaign_service import CampaignService
from app.services.post_service import PostService
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["web-dashboard"])

# TODO: get from auth context
PLACEHOLDER_USER_ID = UUID("00000000-0000-0000-0000-000000000000")


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Marketing dashboard with active campaigns, upcoming posts, and quick stats."""
    campaign_svc = CampaignService(db)
    post_svc = PostService(db)

    # Active campaigns (limit 5)
    active_campaigns = campaign_svc.list_all(status=CampaignStatus.active, limit=5)

    # Upcoming posts (next 7 days, limit 10)
    upcoming_posts = post_svc.list_scheduled(days_ahead=7)[:10]

    # Channel statuses
    channels = list(
        db.scalars(select(Channel).order_by(Channel.name)).all()
    )

    # Quick stats
    total_assets = db.scalar(select(func.count(Asset.id))) or 0

    # TODO: get from auth context
    my_tasks_count = db.scalar(
        select(func.count(Task.id)).where(
            Task.assignee_id == PLACEHOLDER_USER_ID
        )
    ) or 0

    total_campaigns = campaign_svc.count()
    total_posts = db.scalar(select(func.count(Post.id))) or 0

    ctx = {
        "request": request,
        "title": "Dashboard",
        "active_campaigns": active_campaigns,
        "upcoming_posts": upcoming_posts,
        "channels": channels,
        "stats": {
            "total_assets": total_assets,
            "my_tasks": my_tasks_count,
            "total_campaigns": total_campaigns,
            "total_posts": total_posts,
        },
    }
    return templates.TemplateResponse("dashboard/index.html", ctx)
