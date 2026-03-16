"""Calendar view for scheduled posts — monthly/weekly with filters."""

from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.post import Post
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
    today = date.today()
    view_year = year if year else today.year
    view_month = month if month else today.month

    # Clamp to valid range
    view_month = max(1, min(12, view_month))

    # Determine date range based on view mode
    if view == "week":
        if week_start:
            try:
                ws = date.fromisoformat(week_start)
            except ValueError:
                ws = today - timedelta(days=today.weekday())
        else:
            ws = today - timedelta(days=today.weekday())  # Monday
        we = ws + timedelta(days=6)
        start = datetime(ws.year, ws.month, ws.day, tzinfo=UTC)
        end = datetime(we.year, we.month, we.day, 23, 59, 59, tzinfo=UTC)
        view_year = ws.year
        view_month = ws.month
    else:
        _, last_day = calendar.monthrange(view_year, view_month)
        start = datetime(view_year, view_month, 1, tzinfo=UTC)
        end = datetime(view_year, view_month, last_day, 23, 59, 59, tzinfo=UTC)
        ws = None
        we = None

    # Query posts with filters
    stmt = (
        select(Post)
        .where(Post.scheduled_at.isnot(None))
        .where(Post.scheduled_at >= start)
        .where(Post.scheduled_at <= end)
    )
    if campaign_id is not None:
        stmt = stmt.where(Post.campaign_id == campaign_id)
    if channel_id is not None:
        stmt = stmt.where(Post.channel_id == channel_id)
    stmt = stmt.order_by(Post.scheduled_at)
    posts = list(db.scalars(stmt).all())

    # Group posts by date
    posts_by_date: dict[str, list[Post]] = defaultdict(list)
    for post in posts:
        if post.scheduled_at:
            day_key = post.scheduled_at.strftime("%Y-%m-%d")
            posts_by_date[day_key].append(post)

    # Month navigation
    if view_month == 1:
        prev_month, prev_year = 12, view_year - 1
    else:
        prev_month, prev_year = view_month - 1, view_year

    if view_month == 12:
        next_month, next_year = 1, view_year + 1
    else:
        next_month, next_year = view_month + 1, view_year

    # Calendar grid data (month view)
    cal = calendar.Calendar(firstweekday=0)
    month_days = list(cal.itermonthdays2(view_year, view_month))

    # Week view data
    week_days = []
    if view == "week" and ws:
        for i in range(7):
            d = ws + timedelta(days=i)
            week_days.append(d)

    # Filter dropdowns data
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
        "year": view_year,
        "month": view_month,
        "month_name": calendar.month_name[view_month],
        "posts_by_date": dict(posts_by_date),
        "posts": posts,
        "prev_month": prev_month,
        "prev_year": prev_year,
        "next_month": next_month,
        "next_year": next_year,
        "month_days": month_days,
        "today": today.isoformat(),
        "view": view,
        "week_days": week_days,
        "week_start": ws.isoformat() if ws else "",
        "prev_week": (ws - timedelta(days=7)).isoformat() if ws else "",
        "next_week": (ws + timedelta(days=7)).isoformat() if ws else "",
        "campaigns": campaigns,
        "channels": channels,
        "campaign_id_filter": str(campaign_id) if campaign_id else "",
        "channel_id_filter": str(channel_id) if channel_id else "",
        "filter_qs": filter_qs,
    }
    return templates.TemplateResponse("calendar/index.html", ctx)
