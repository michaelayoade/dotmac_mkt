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
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["web-analytics"])


def _parse_date(value: str | None, default: date) -> date:
    """Parse an ISO date string, falling back to default."""
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


@router.get("", response_class=HTMLResponse)
def analytics_overview(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Analytics overview with aggregated metrics for a date range."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    analytics_svc = AnalyticsService(db)
    overview = analytics_svc.get_overview(start_date=d_start, end_date=d_end)

    # Also list campaigns for drill-down links
    campaign_svc = CampaignService(db)
    campaigns = campaign_svc.list_all(limit=50)

    # Per-channel breakdown for the table
    channel_svc = ChannelService(db)
    channels = channel_svc.list_all()
    channel_metrics = []
    for ch in channels:
        ch_metrics = analytics_svc.get_channel_metrics(
            ch.id, start_date=d_start, end_date=d_end
        )
        totals: dict[str, float] = {}
        for m in ch_metrics:
            totals[m.metric_type.value] = totals.get(m.metric_type.value, 0) + float(m.value)
        channel_metrics.append({
            "channel_name": ch.name,
            "impressions": int(totals.get("impressions", 0)),
            "reach": int(totals.get("reach", 0)),
            "clicks": int(totals.get("clicks", 0)),
            "engagement": int(totals.get("engagement", 0)),
        })

    # Daily totals for time-series chart
    daily_totals = analytics_svc.get_daily_totals(start_date=d_start, end_date=d_end)

    # Preset date ranges for quick links
    preset_dates = [
        {"label": "7 days", "start": (today - timedelta(days=7)).isoformat(), "end": today.isoformat()},
        {"label": "30 days", "start": (today - timedelta(days=30)).isoformat(), "end": today.isoformat()},
        {"label": "90 days", "start": (today - timedelta(days=90)).isoformat(), "end": today.isoformat()},
    ]

    ctx = {
        "request": request,
        "title": "Analytics",
        "overview": overview,
        "campaigns": campaigns,
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
        "total_impressions": int(overview.get("impressions", 0)),
        "total_reach": int(overview.get("reach", 0)),
        "total_clicks": int(overview.get("clicks", 0)),
        "total_engagement": int(overview.get("engagement", 0)),
        "channel_metrics": channel_metrics,
        "daily_totals": daily_totals,
        "preset_dates": preset_dates,
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
                channel_data[ch_id][m.metric_type.value] = (
                    channel_data[ch_id].get(m.metric_type.value, 0) + float(m.value)
                )

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
    writer.writerow(
        ["date", "channel_id", "post_id", "metric_type", "value"]
    )
    for m in metrics:
        writer.writerow([
            m.metric_date.isoformat(),
            str(m.channel_id),
            str(m.post_id) if m.post_id else "",
            m.metric_type.value,
            str(float(m.value)),
        ])

    output.seek(0)
    filename = f"analytics_{d_start}_{d_end}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
