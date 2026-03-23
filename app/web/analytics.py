"""Analytics web routes — overview, campaign drill-down, CSV export."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.analytics_service import AnalyticsService
from app.services.campaign_service import CampaignService
from app.services.channel_service import ChannelService
from app.services.common import coerce_uuid
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["web-analytics"])

METRIC_STYLES = {
    "impressions": ("Impressions", "#6366f1"),
    "reach": ("Reach", "#22c55e"),
    "clicks": ("Clicks", "#eab308"),
    "engagement": ("Engagement", "#ef4444"),
    "spend": ("Spend", "#0f766e"),
    "conversions": ("Conversions", "#0891b2"),
    "likes": ("Likes", "#db2777"),
    "shares": ("Shares", "#7c3aed"),
    "retweets": ("Retweets", "#2563eb"),
    "sessions": ("Sessions", "#0ea5e9"),
    "pageviews": ("Pageviews", "#14b8a6"),
    "users": ("Users", "#84cc16"),
    "bounce_rate": ("Bounce Rate", "#f97316"),
}
FALLBACK_COLORS = (
    "#6366f1",
    "#22c55e",
    "#eab308",
    "#ef4444",
    "#0ea5e9",
    "#db2777",
    "#7c3aed",
    "#14b8a6",
)


def _has_metric_data(
    overview: dict[str, float], daily_metric_breakdown: list[dict[str, str | float]]
) -> bool:
    return any(float(total) > 0 for total in overview.values()) or bool(
        daily_metric_breakdown
    )


def _parse_date(value: str | None, default: date) -> date:
    """Parse an ISO date string, falling back to default."""
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


def _parse_uuid(value: str | None) -> UUID | None:
    """Parse a UUID string, returning None when invalid or absent."""
    if not value:
        return None
    try:
        return coerce_uuid(value)
    except ValueError:
        return None


def _prepare_chart_channel_metrics(
    channel_metrics: list[dict[str, object]],
    metric_keys: list[str],
) -> list[dict[str, object]]:
    """Drop all-zero channels from visual charts to keep them readable."""
    return [
        row
        for row in channel_metrics
        if any(float(row["metrics"].get(metric, 0)) > 0 for metric in metric_keys)
    ]


def _metric_style(metric_key: str, index: int = 0) -> tuple[str, str]:
    if metric_key in METRIC_STYLES:
        return METRIC_STYLES[metric_key]
    return (
        metric_key.replace("_", " ").title(),
        FALLBACK_COLORS[index % len(FALLBACK_COLORS)],
    )


def _build_time_series_chart(
    daily_rows: list[dict[str, str | float]],
    metric_keys: list[str],
) -> dict:
    """Build lightweight SVG chart data for the analytics template."""
    if not daily_rows or not metric_keys:
        return {}

    grouped: dict[str, dict[str, float]] = {}
    for row in daily_rows:
        grouped.setdefault(str(row["date"]), {})
        grouped[str(row["date"])][str(row["metric_type"])] = float(row["total"])
    dates = sorted(grouped.keys())

    width = 760
    height = 220
    pad_x = 20
    pad_y = 20
    inner_width = width - (pad_x * 2)
    inner_height = height - (pad_y * 2)
    max_value = max(
        max(float(grouped[d].get(metric, 0)) for metric in metric_keys) for d in dates
    )
    if max_value <= 0:
        max_value = 1

    point_count = len(dates)
    denominator = max(point_count - 1, 1)
    series = []
    for index, metric in enumerate(metric_keys):
        label, color = _metric_style(metric, index)
        points = []
        markers = []
        for point_index, chart_date in enumerate(dates):
            x = pad_x + (inner_width * point_index / denominator)
            if point_count == 1:
                x = width / 2
            value = float(grouped[chart_date].get(metric, 0))
            y = height - pad_y - ((value / max_value) * inner_height)
            points.append(f"{x:.1f},{y:.1f}")
            markers.append(
                {
                    "x": round(x, 1),
                    "y": round(y, 1),
                    "value": value,
                    "date": chart_date,
                }
            )
        series.append(
            {
                "key": metric,
                "label": label,
                "color": color,
                "points": " ".join(points),
                "markers": markers,
            }
        )

    return {
        "width": width,
        "height": height,
        "max_value": max_value,
        "series": series,
        "labels": [{"date": d, "short": d[5:]} for d in dates],
        "grid_lines": [{"y": pad_y + (inner_height * step / 4)} for step in range(5)],
    }


def _build_channel_strengths(
    channel_metrics: list[dict[str, object]],
    metric_keys: list[str],
) -> list[dict[str, object]]:
    """Normalize per-channel metrics for a non-JS strengths view."""
    if not channel_metrics or not metric_keys:
        return []

    maxima = {
        metric: max(float(row["metrics"].get(metric, 0)) for row in channel_metrics)
        or 1
        for metric in metric_keys
    }
    strengths = []
    for row in channel_metrics:
        metrics = []
        for index, metric in enumerate(metric_keys):
            label, color = _metric_style(metric, index)
            value = float(row["metrics"].get(metric, 0))
            metrics.append(
                {
                    "key": metric,
                    "label": label,
                    "value": value,
                    "pct": round((value / maxima[metric]) * 100)
                    if maxima[metric]
                    else 0,
                    "color": color,
                }
            )
        strengths.append(
            {
                "channel_name": row.get("channel_name", "Unknown"),
                "metrics": metrics,
            }
        )
    return strengths


@router.get("", response_class=HTMLResponse)
def analytics_overview(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    metric_date: str | None = None,
    post_id: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Analytics overview with aggregated metrics for a date range."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)
    d_metric = _parse_date(metric_date, d_end) if metric_date else None
    selected_post_id = _parse_uuid(post_id)

    analytics_svc = AnalyticsService(db)
    overview = analytics_svc.get_overview(
        start_date=d_start,
        end_date=d_end,
        post_id=selected_post_id,
        metric_date=d_metric,
    )

    # Also list campaigns for drill-down links
    campaign_svc = CampaignService(db)
    campaigns = campaign_svc.list_all(limit=50)

    # Daily totals for time-series chart
    daily_totals = analytics_svc.get_daily_totals(
        start_date=d_start,
        end_date=d_end,
        post_id=selected_post_id,
        metric_date=d_metric,
    )
    daily_metric_breakdown = analytics_svc.get_daily_metric_breakdown(
        start_date=d_start,
        end_date=d_end,
        post_id=selected_post_id,
        metric_date=d_metric,
    )

    # Channel-level metrics are often available even when a post filter has no
    # post-scoped analytics. Fall back so the overview charts do not go blank.
    if selected_post_id and not _has_metric_data(overview, daily_metric_breakdown):
        overview = analytics_svc.get_overview(
            start_date=d_start,
            end_date=d_end,
            metric_date=d_metric,
        )
        daily_totals = analytics_svc.get_daily_totals(
            start_date=d_start,
            end_date=d_end,
            metric_date=d_metric,
        )
        daily_metric_breakdown = analytics_svc.get_daily_metric_breakdown(
            start_date=d_start,
            end_date=d_end,
            metric_date=d_metric,
        )

    # Per-channel breakdown for the table
    channel_svc = ChannelService(db)
    channels = channel_svc.list_all()
    channel_metrics = []
    visual_channel_metrics = []
    available_metric_keys: set[str] = set()
    for ch in channels:
        ch_metrics = analytics_svc.get_channel_metrics(
            ch.id,
            start_date=d_start,
            end_date=d_end,
            metric_date=d_metric,
        )
        totals: dict[str, float] = {}
        for m in ch_metrics:
            totals[m.metric_type.value] = totals.get(m.metric_type.value, 0) + float(
                m.value
            )
        available_metric_keys.update(key for key, value in totals.items() if value > 0)
        channel_metrics.append(
            {
                "channel_name": ch.name,
                "impressions": int(totals.get("impressions", 0)),
                "reach": int(totals.get("reach", 0)),
                "clicks": int(totals.get("clicks", 0)),
                "engagement": int(totals.get("engagement", 0)),
            }
        )
        visual_channel_metrics.append({"channel_name": ch.name, "metrics": totals})

    active_metric_keys = [
        key for key, total in overview.items() if float(total) > 0
    ] or sorted(available_metric_keys)
    chart_channel_metrics = _prepare_chart_channel_metrics(
        visual_channel_metrics, active_metric_keys
    )
    time_series_chart = _build_time_series_chart(
        daily_metric_breakdown, active_metric_keys
    )
    channel_strengths = _build_channel_strengths(
        chart_channel_metrics, active_metric_keys
    )
    post_filter_options = analytics_svc.get_post_filter_options(
        start_date=d_start, end_date=d_end
    )
    post_impressions = analytics_svc.get_post_impression_rows(
        start_date=d_start,
        end_date=d_end,
        post_id=selected_post_id,
        metric_date=d_metric,
    )
    selected_post = next(
        (
            option
            for option in post_filter_options
            if option["id"] == str(selected_post_id)
        ),
        None,
    )

    # Preset date ranges for quick links
    preset_dates = [
        {
            "label": "7 days",
            "start": (today - timedelta(days=7)).isoformat(),
            "end": today.isoformat(),
        },
        {
            "label": "30 days",
            "start": (today - timedelta(days=30)).isoformat(),
            "end": today.isoformat(),
        },
        {
            "label": "90 days",
            "start": (today - timedelta(days=90)).isoformat(),
            "end": today.isoformat(),
        },
    ]

    ctx = {
        "request": request,
        "title": "Analytics",
        "overview": overview,
        "campaigns": campaigns,
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
        "today_iso": today.isoformat(),
        "metric_date": d_metric.isoformat() if d_metric else "",
        "total_impressions": int(overview.get("impressions", 0)),
        "total_reach": int(overview.get("reach", 0)),
        "total_clicks": int(overview.get("clicks", 0)),
        "total_engagement": int(overview.get("engagement", 0)),
        "channel_metrics": channel_metrics,
        "chart_channel_metrics": chart_channel_metrics,
        "time_series_chart": time_series_chart,
        "channel_strengths": channel_strengths,
        "daily_totals": daily_totals,
        "active_metric_keys": active_metric_keys,
        "preset_dates": preset_dates,
        "post_filter_options": post_filter_options,
        "post_impressions": post_impressions,
        "selected_post_id": str(selected_post_id) if selected_post_id else "",
        "selected_post": selected_post,
    }
    return templates.TemplateResponse("analytics/index.html", ctx)


@router.get("/campaign/{id}", response_class=HTMLResponse)
def campaign_analytics(
    request: Request,
    id: UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Analytics for a specific campaign."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)

    analytics_svc = AnalyticsService(db)
    metrics = analytics_svc.get_campaign_metrics(id, start_date=d_start, end_date=d_end)

    # Build per-channel breakdown for the template
    from sqlalchemy import func, select

    from app.models.channel import Channel
    from app.models.post import Post

    # Batch-load all posts referenced by metrics in a single query
    post_ids = {m.post_id for m in metrics if m.post_id}
    posts_by_id: dict = {}
    if post_ids:
        post_rows = list(
            db.execute(
                select(Post, Channel)
                .outerjoin(Channel, Post.channel_id == Channel.id)
                .where(Post.id.in_(post_ids))
            ).all()
        )
        for post, channel in post_rows:
            posts_by_id[post.id] = (post, channel)

    channel_data: dict[str, dict] = {}
    for m in metrics:
        if m.post_id and m.post_id in posts_by_id:
            post, channel = posts_by_id[m.post_id]
            if channel:
                ch_id = str(post.channel_id)
                if ch_id not in channel_data:
                    channel_data[ch_id] = {
                        "channel_name": channel.name,
                        "posts_count": 0,
                        "impressions": 0,
                        "reach": 0,
                        "clicks": 0,
                        "engagement": 0,
                    }
                channel_data[ch_id][m.metric_type.value] = channel_data[ch_id].get(
                    m.metric_type.value, 0
                ) + float(m.value)

    # Count posts per channel in this campaign
    post_counts = db.execute(
        select(Post.channel_id, func.count(Post.id))
        .where(Post.campaign_id == id)
        .group_by(Post.channel_id)
    ).all()
    for ch_id_val, count in post_counts:
        key = str(ch_id_val)
        if key in channel_data:
            channel_data[key]["posts_count"] = count

    channel_metrics = list(channel_data.values())

    ctx = {
        "request": request,
        "title": f"Analytics — {campaign.name if campaign else 'Campaign'}",
        "campaign": campaign,
        "metrics": metrics,
        "channel_metrics": channel_metrics,
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
    }
    return templates.TemplateResponse("analytics/campaign.html", ctx)


@router.get("/export")
def export_metrics_csv(
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> StreamingResponse:
    """Export analytics metrics as CSV for a date range."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    # Fetch all channel metrics for the range
    from sqlalchemy import select

    from app.models.channel_metric import ChannelMetric

    stmt = (
        select(ChannelMetric)
        .where(ChannelMetric.metric_date >= d_start)
        .where(ChannelMetric.metric_date <= d_end)
        .order_by(ChannelMetric.metric_date, ChannelMetric.channel_id)
    )
    metrics = list(db.scalars(stmt).all())

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "channel_id", "post_id", "metric_type", "value"])
    for m in metrics:
        writer.writerow(
            [
                m.metric_date.isoformat(),
                str(m.channel_id),
                str(m.post_id) if m.post_id else "",
                m.metric_type.value,
                str(float(m.value)),
            ]
        )

    output.seek(0)
    filename = f"analytics_{d_start}_{d_end}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
