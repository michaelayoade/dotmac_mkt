"""Centralized Jinja2 environment with custom filters.

All template rendering should use this module's ``templates`` object
instead of creating ad-hoc ``Jinja2Templates`` instances.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, date, datetime

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


# ── Filters ──────────────────────────────────────────────


def _sanitize_html(value: str | None) -> str:
    """Strip all HTML tags from user content. Safe for template output."""
    if not value:
        return ""
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", "", str(value))
    return html.escape(clean)


def _nl2br(value: str | None) -> str:
    """Convert newlines to ``<br>`` tags for display."""
    if not value:
        return ""
    escaped = html.escape(str(value))
    return escaped.replace("\n", "<br>\n")


def _format_date(value: date | datetime | None, fmt: str = "%d %b %Y") -> str:
    """Format a date/datetime for display. Returns empty string for None."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(fmt)
    if isinstance(value, date):
        return value.strftime(fmt)
    return str(value)


def _format_datetime(value: datetime | None, fmt: str = "%d %b %Y %H:%M") -> str:
    """Format a datetime with time component."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(fmt)
    return str(value)


def _format_currency(
    value: float | int | None,
    symbol: str = "$",
    decimals: int = 2,
) -> str:
    """Format a number as currency."""
    if value is None:
        return ""
    formatted = f"{value:,.{decimals}f}"
    return f"{symbol}{formatted}"


def _format_number(value: float | int | None, decimals: int = 2) -> str:
    """Format a number with thousands separators."""
    if value is None:
        return ""
    return f"{value:,.{decimals}f}"


def _timeago(value: datetime | None) -> str:
    """Produce a human-readable 'time ago' string."""
    if value is None:
        return ""
    now = datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    diff = now - value
    seconds = int(diff.total_seconds())

    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


# ── Register filters ─────────────────────────────────────

templates.env.filters["sanitize_html"] = _sanitize_html
templates.env.filters["nl2br"] = _nl2br
templates.env.filters["format_date"] = _format_date
templates.env.filters["format_datetime"] = _format_datetime
templates.env.filters["format_currency"] = _format_currency
templates.env.filters["format_number"] = _format_number
templates.env.filters["timeago"] = _timeago
