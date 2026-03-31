"""Date logic and post grouping for the calendar view."""

from __future__ import annotations

import calendar as cal_mod
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.post import Post

logger = logging.getLogger(__name__)


@dataclass
class DateRange:
    start: datetime
    end: datetime


@dataclass
class MonthNavigation:
    prev_month: int
    prev_year: int
    next_month: int
    next_year: int


@dataclass
class CalendarData:
    year: int
    month: int
    month_name: str
    posts_by_date: dict[str, list]
    posts: list
    navigation: MonthNavigation
    month_days: list[tuple[int, int]]
    today_iso: str
    view: str
    week_days: list[date] = field(default_factory=list)
    week_start: str = ""
    prev_week: str = ""
    next_week: str = ""


class CalendarService:
    """Date logic and post grouping for the calendar view."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_date_range(
        self,
        *,
        view: str,
        year: int,
        month: int,
        week_start: date | None = None,
    ) -> tuple[DateRange, date | None]:
        """Calculate start/end datetime for month or week view.

        Returns (DateRange, week_start_date_or_None).
        """
        if view == "week":
            ws = (
                week_start
                if week_start
                else date.today() - timedelta(days=date.today().weekday())
            )
            we = ws + timedelta(days=6)
            return (
                DateRange(
                    start=datetime(ws.year, ws.month, ws.day, tzinfo=UTC),
                    end=datetime(we.year, we.month, we.day, 23, 59, 59, tzinfo=UTC),
                ),
                ws,
            )

        _, last_day = cal_mod.monthrange(year, month)
        return (
            DateRange(
                start=datetime(year, month, 1, tzinfo=UTC),
                end=datetime(year, month, last_day, 23, 59, 59, tzinfo=UTC),
            ),
            None,
        )

    @staticmethod
    def get_month_navigation(*, year: int, month: int) -> MonthNavigation:
        """Calculate prev/next month and year values."""
        if month == 1:
            prev_month, prev_year = 12, year - 1
        else:
            prev_month, prev_year = month - 1, year

        if month == 12:
            next_month, next_year = 1, year + 1
        else:
            next_month, next_year = month + 1, year

        return MonthNavigation(
            prev_month=prev_month,
            prev_year=prev_year,
            next_month=next_month,
            next_year=next_year,
        )

    @staticmethod
    def get_calendar_grid(*, year: int, month: int) -> list[tuple[int, int]]:
        """Generate (day_number, weekday) tuples for the month grid."""
        cal = cal_mod.Calendar(firstweekday=0)
        return list(cal.itermonthdays2(year, month))

    @staticmethod
    def get_week_days(*, week_start: date) -> list[date]:
        """Generate list of 7 date objects starting from week_start."""
        return [week_start + timedelta(days=i) for i in range(7)]

    def get_posts_for_range(
        self,
        *,
        start: datetime,
        end: datetime,
        campaign_id: UUID | None = None,
        channel_id: UUID | None = None,
    ) -> list[Post]:
        """Query posts with scheduled_at in range, with optional filters."""
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
        return list(self.db.scalars(stmt).all())

    @staticmethod
    def group_posts_by_date(posts: list[Post]) -> dict[str, list[Post]]:
        """Group posts into {YYYY-MM-DD: [post, ...]} dict."""
        result: dict[str, list[Post]] = defaultdict(list)
        for post in posts:
            if post.scheduled_at:
                day_key = post.scheduled_at.strftime("%Y-%m-%d")
                result[day_key].append(post)
        return dict(result)

    def get_calendar_data(
        self,
        *,
        view: str = "month",
        year: int | None = None,
        month: int | None = None,
        week_start_str: str | None = None,
        campaign_id: UUID | None = None,
        channel_id: UUID | None = None,
    ) -> CalendarData:
        """One-call method that assembles the full calendar context."""
        today = date.today()
        view_year = year if year else today.year
        view_month = month if month else today.month
        view_month = max(1, min(12, view_month))

        # Parse week_start
        ws_date: date | None = None
        if view == "week" and week_start_str:
            try:
                ws_date = date.fromisoformat(week_start_str)
            except ValueError:
                ws_date = None

        date_range, ws = self.get_date_range(
            view=view, year=view_year, month=view_month, week_start=ws_date
        )

        if ws:
            view_year = ws.year
            view_month = ws.month

        posts = self.get_posts_for_range(
            start=date_range.start,
            end=date_range.end,
            campaign_id=campaign_id,
            channel_id=channel_id,
        )
        posts_by_date = self.group_posts_by_date(posts)
        navigation = self.get_month_navigation(year=view_year, month=view_month)
        month_days = self.get_calendar_grid(year=view_year, month=view_month)

        week_days: list[date] = []
        week_start_iso = ""
        prev_week = ""
        next_week = ""
        if view == "week" and ws:
            week_days = self.get_week_days(week_start=ws)
            week_start_iso = ws.isoformat()
            prev_week = (ws - timedelta(days=7)).isoformat()
            next_week = (ws + timedelta(days=7)).isoformat()

        return CalendarData(
            year=view_year,
            month=view_month,
            month_name=cal_mod.month_name[view_month],
            posts_by_date=posts_by_date,
            posts=posts,
            navigation=navigation,
            month_days=month_days,
            today_iso=today.isoformat(),
            view=view,
            week_days=week_days,
            week_start=week_start_iso,
            prev_week=prev_week,
            next_week=next_week,
        )
