"""Marketing dashboard — campaign overview, upcoming posts, quick stats."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.asset import Asset, DriveStatus
from app.models.campaign import CampaignStatus
from app.models.channel import Channel, ChannelStatus
from app.models.task import Task, TaskStatus
from app.services.analytics_service import AnalyticsService
from app.services.campaign_service import CampaignService
from app.services.post_service import PostService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["web-dashboard"])


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
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
    person_id = UUID(auth["person_id"])
    total_assets = db.scalar(
        select(func.count(Asset.id)).where(Asset.drive_status != DriveStatus.missing)
    ) or 0
    total_campaigns = campaign_svc.count()
    active_tasks = db.scalar(
        select(func.count(Task.id)).where(
            Task.status.in_([TaskStatus.todo, TaskStatus.in_progress]),
            Task.assignee_id == person_id,
        )
    ) or 0
    connected_channels = db.scalar(
        select(func.count(Channel.id)).where(
            Channel.status == ChannelStatus.connected
        )
    ) or 0

    # Channel health for badges
    channel_health = [
        {
            "name": ch.name,
            "status": (
                "healthy" if ch.status == ChannelStatus.connected
                else ("error" if ch.status == ChannelStatus.error else "disconnected")
            ),
        }
        for ch in channels
    ]

    # Sparkline data: daily impressions for last 7 days
    today_date = date.today()
    analytics_svc = AnalyticsService(db)
    sparkline_data = analytics_svc.get_daily_totals(
        start_date=today_date - timedelta(days=6), end_date=today_date
    )

    # Percent change vs prior 7 days
    prior_data = analytics_svc.get_daily_totals(
        start_date=today_date - timedelta(days=13), end_date=today_date - timedelta(days=7)
    )
    current_impressions = sum(d["impressions"] for d in sparkline_data)
    prior_impressions = sum(d["impressions"] for d in prior_data)
    impressions_change = (
        round((current_impressions - prior_impressions) / prior_impressions * 100, 1)
        if prior_impressions > 0
        else 0.0
    )

    # Campaign status counts for donut chart
    campaign_status_counts = {}
    for status in CampaignStatus:
        campaign_status_counts[status.value] = campaign_svc.count(status=status)

    ctx = {
        "request": request,
        "title": "Dashboard",
        "active_campaigns": active_campaigns,
        "upcoming_posts": upcoming_posts,
        "channels": channels,
        "total_campaigns": total_campaigns,
        "total_assets": total_assets,
        "active_tasks": active_tasks,
        "connected_channels": connected_channels,
        "channel_health": channel_health,
        "sparkline_data": sparkline_data,
        "impressions_change": impressions_change,
        "campaign_status_counts": campaign_status_counts,
    }
    return templates.TemplateResponse("dashboard/index.html", ctx)
