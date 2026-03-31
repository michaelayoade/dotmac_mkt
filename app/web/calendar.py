"""Calendar view for scheduled posts — monthly/weekly with filters."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.calendar_service import CalendarService
from app.services.campaign_service import CampaignService
from app.services.channel_service import ChannelService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["web-calendar"])


@router.get("", response_class=HTMLResponse)
def calendar_view(
    request: Request,
    month: int | None = None,
    year: int | None = None,
    view: str = "month",
    week_start: str | None = None,
    campaign_id: UUID | None = None,
    channel_id: UUID | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Calendar view showing posts grouped by scheduled date."""
    cal_svc = CalendarService(db)
    data = cal_svc.get_calendar_data(
        view=view,
        year=year,
        month=month,
        week_start_str=week_start,
        campaign_id=campaign_id,
        channel_id=channel_id,
    )

    # Filter dropdowns
    campaign_svc = CampaignService(db)
    channel_svc = ChannelService(db)
    campaigns = campaign_svc.list_all(limit=100)
    channels = channel_svc.list_all()

    # Build filter query string for nav links
    filter_qs = ""
    if campaign_id:
        filter_qs += f"&campaign_id={campaign_id}"
    if channel_id:
        filter_qs += f"&channel_id={channel_id}"

    ctx = {
        "request": request,
        "title": "Calendar",
        "year": data.year,
        "month": data.month,
        "month_name": data.month_name,
        "posts_by_date": data.posts_by_date,
        "posts": data.posts,
        "prev_month": data.navigation.prev_month,
        "prev_year": data.navigation.prev_year,
        "next_month": data.navigation.next_month,
        "next_year": data.navigation.next_year,
        "month_days": data.month_days,
        "today": data.today_iso,
        "view": data.view,
        "week_days": data.week_days,
        "week_start": data.week_start,
        "prev_week": data.prev_week,
        "next_week": data.next_week,
        "campaigns": campaigns,
        "channels": channels,
        "campaign_id_filter": str(campaign_id) if campaign_id else "",
        "channel_id_filter": str(channel_id) if channel_id else "",
        "filter_qs": filter_qs,
    }
    return templates.TemplateResponse("calendar/index.html", ctx)
