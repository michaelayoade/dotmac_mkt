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
from app.templates import templates

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

    ctx = {
        "request": request,
        "title": "Analytics",
        "overview": overview,
        "campaigns": campaigns,
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
    }
    return templates.TemplateResponse("analytics/index.html", ctx)


@router.get("/campaign/{id}", response_class=HTMLResponse)
def campaign_analytics(
    request: Request,
    id: UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Analytics for a specific campaign."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)

    analytics_svc = AnalyticsService(db)
    metrics = analytics_svc.get_campaign_metrics(id, start_date=d_start, end_date=d_end)

    ctx = {
        "request": request,
        "title": f"Analytics — {campaign.name if campaign else 'Campaign'}",
        "campaign": campaign,
        "metrics": metrics,
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
    }
    return templates.TemplateResponse("analytics/campaign.html", ctx)


@router.get("/export")
def export_metrics_csv(
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export analytics metrics as CSV for a date range."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    AnalyticsService(db)

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
