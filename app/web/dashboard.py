"""Marketing dashboard — campaign overview, upcoming posts, quick stats."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.dashboard_service import DashboardService
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
    person_id = UUID(auth["person_id"])
    svc = DashboardService(db)
    data = svc.get_dashboard_data(person_id=person_id)

    ctx = {
        "request": request,
        "title": "Dashboard",
        "active_campaigns": data.active_campaigns,
        "upcoming_posts": data.upcoming_posts,
        "channels": data.channels,
        "total_campaigns": data.quick_stats.total_campaigns,
        "total_assets": data.quick_stats.total_assets,
        "active_tasks": data.quick_stats.active_tasks,
        "connected_channels": data.quick_stats.connected_channels,
        "channel_health": [
            {"name": h.name, "status": h.status} for h in data.channel_health
        ],
        "sparkline_data": data.sparkline_data,
        "impressions_change": data.impressions_change,
        "campaign_status_counts": data.campaign_status_counts,
    }
    return templates.TemplateResponse("dashboard/index.html", ctx)
