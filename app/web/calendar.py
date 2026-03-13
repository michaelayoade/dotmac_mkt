"""Calendar view for scheduled posts."""

from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.post import Post
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["web-calendar"])


@router.get("", response_class=HTMLResponse)
def calendar_view(
    request: Request,
    month: int | None = None,
    year: int | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Calendar view showing posts grouped by scheduled date."""
    today = date.today()
    view_year = year if year else today.year
    view_month = month if month else today.month

    # Clamp to valid range
    if view_month < 1:
        view_month = 1
    elif view_month > 12:
        view_month = 12

    # Determine the date range for the month
    _, last_day = calendar.monthrange(view_year, view_month)
    start = datetime(view_year, view_month, 1, tzinfo=UTC)
    end = datetime(view_year, view_month, last_day, 23, 59, 59, tzinfo=UTC)

    # Query all posts scheduled in this month
    stmt = (
        select(Post)
        .where(Post.scheduled_at.isnot(None))
        .where(Post.scheduled_at >= start)
        .where(Post.scheduled_at <= end)
        .order_by(Post.scheduled_at)
    )
    posts = list(db.scalars(stmt).all())

    # Group posts by date
    posts_by_date: dict[str, list[Post]] = defaultdict(list)
    for post in posts:
        if post.scheduled_at:
            day_key = post.scheduled_at.strftime("%Y-%m-%d")
            posts_by_date[day_key].append(post)

    # Calculate prev/next month for navigation
    if view_month == 1:
        prev_month, prev_year = 12, view_year - 1
    else:
        prev_month, prev_year = view_month - 1, view_year

    if view_month == 12:
        next_month, next_year = 1, view_year + 1
    else:
        next_month, next_year = view_month + 1, view_year

    # Calendar grid data
    cal = calendar.Calendar(firstweekday=0)  # Monday start
    month_days = list(cal.itermonthdays2(view_year, view_month))

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
    }
    return templates.TemplateResponse("calendar/index.html", ctx)
