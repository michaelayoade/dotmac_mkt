"""Analytics web routes — overview, campaign drill-down, CSV export."""

from __future__ import annotations

import contextlib
import csv
import io
import logging
from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.adapters.registry import get_adapter
from app.api.deps import get_db
from app.models.ad_campaign import AdPlatform
from app.models.channel import ChannelProvider, ChannelStatus
from app.services.ad_dashboard_service import AdDashboardService
from app.services.analytics_chart_service import AnalyticsChartService
from app.services.analytics_service import AnalyticsService
from app.services.campaign_service import CampaignService
from app.services.channel_integration_settings import get_meta_oauth_config
from app.services.channel_service import ChannelService
from app.services.common import coerce_uuid
from app.services.credential_service import CredentialService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["web-analytics"])


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


def _meta_ads_summary(rows: list[dict[str, object]]) -> dict[str, float]:
    totals = {
        "impressions": 0.0,
        "reach": 0.0,
        "clicks": 0.0,
        "spend": 0.0,
        "conversions": 0.0,
    }
    for row in rows:
        for key in totals:
            totals[key] += float(row.get(key, 0) or 0)
    return totals


def _recompute_meta_ads_derived_metrics(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        impressions = float(row.get("impressions", 0) or 0)
        clicks = float(row.get("clicks", 0) or 0)
        reach = float(row.get("reach", 0) or 0)
        spend = float(row.get("spend", 0) or 0)
        normalized.append(
            {
                **row,
                "ctr": (clicks / impressions * 100) if impressions > 0 else 0.0,
                "cpc": (spend / clicks) if clicks > 0 else 0.0,
                "cpp": (spend / reach) if reach > 0 else 0.0,
            }
        )
    return normalized


def _currency_prefix(currency_code: str) -> str:
    code = currency_code.strip().upper()
    if not code or code == "MULTI":
        return ""
    return f"{code} "


def _resolve_currency_code(rows: list[dict[str, object]], default: str = "NGN") -> str:
    currencies = {
        str(row.get("account_currency", "")).strip().upper()
        for row in rows
        if str(row.get("account_currency", "")).strip()
    }
    if len(currencies) == 1:
        return next(iter(currencies))
    if not currencies:
        return default
    return "MULTI"


def _filter_meta_ads_rows(
    rows: list[dict[str, object]], campaign: str | None
) -> list[dict[str, object]]:
    if not campaign or not campaign.strip():
        return rows
    selected = campaign.strip()
    return [
        row
        for row in rows
        if selected == str(row.get("campaign_id", "") or "")
        or selected == str(row.get("campaign_name", "") or "")
    ]


def _ads_summary(rows: list[dict[str, object]]) -> dict[str, float]:
    totals = {
        "impressions": 0.0,
        "clicks": 0.0,
        "spend": 0.0,
        "conversions": 0.0,
    }
    for row in rows:
        for key in totals:
            totals[key] += float(row.get(key, 0) or 0)
    return totals


def _coalesce_history_rows(
    rows: list[dict[str, object]],
    *,
    key_fields: tuple[str, ...],
    metric_fields: tuple[str, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, ...], dict[str, object]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "") or "") for field in key_fields)
        if key not in grouped:
            grouped[key] = dict(row)
            continue
        current = grouped[key]
        for metric in metric_fields:
            current[metric] = float(current.get(metric, 0) or 0) + float(
                row.get(metric, 0) or 0
            )
    return list(grouped.values())


def _csv_response(
    filename: str, headers: list[str], rows: list[dict[str, object]]
) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(header, "") for header in headers])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _load_meta_ads_history(
    db: Session, start_date: date, end_date: date
) -> tuple[list[dict[str, object]], list[str], list[object]]:
    channel_svc = ChannelService(db)
    cred_svc = CredentialService() if CredentialService.is_configured() else None
    meta_config = get_meta_oauth_config(db)
    channels = [
        channel
        for channel in channel_svc.list_all(limit=200)
        if channel.provider == ChannelProvider.meta_ads
        and channel.status == ChannelStatus.connected
    ]

    history_rows: list[dict[str, object]] = []
    errors: list[str] = []

    if cred_svc is None:
        errors.append(
            "Encryption key is not configured, so Meta Ads credentials cannot be read."
        )
    else:
        for channel in channels:
            if not channel.credentials_encrypted:
                continue
            creds = cred_svc.decrypt(channel.credentials_encrypted)
            if not creds:
                errors.append(f"Could not decrypt credentials for {channel.name}.")
                continue
            try:
                adapter = get_adapter(
                    ChannelProvider.meta_ads,
                    access_token=creds.get("access_token", ""),
                    account_id=creds.get("account_id")
                    or channel.external_account_id
                    or "",
                    client_id=meta_config.app_id,
                    client_secret=meta_config.app_secret,
                    graph_version=meta_config.graph_version,
                    timeout_seconds=meta_config.api_timeout_seconds,
                )
                rows = await adapter.fetch_ads_history(start_date, end_date)
            except (ValueError, RuntimeError) as exc:
                logger.error("Meta Ads page fetch failed for %s: %s", channel.name, exc)
                errors.append(f"Could not load ads history for {channel.name}.")
                continue

            for row in rows:
                history_rows.append(
                    {
                        **row,
                        "channel_name": channel.name,
                        "account_id": channel.external_account_id or "",
                    }
                )

    history_rows = _coalesce_history_rows(
        history_rows,
        key_fields=(
            "account_id",
            "date_start",
            "campaign_id",
            "adset_id",
            "ad_id",
        ),
        metric_fields=("impressions", "reach", "clicks", "spend", "conversions"),
    )
    history_rows = _recompute_meta_ads_derived_metrics(history_rows)
    history_rows.sort(
        key=lambda item: (
            str(item.get("date_start", "")),
            str(item.get("campaign_name", "")),
            str(item.get("ad_name", "")),
        ),
        reverse=True,
    )
    return history_rows, errors, channels


async def _load_google_ads_history(
    db: Session, start_date: date, end_date: date
) -> tuple[list[dict[str, object]], list[str], list[object]]:
    channel_svc = ChannelService(db)
    cred_svc = CredentialService() if CredentialService.is_configured() else None
    channels = [
        channel
        for channel in channel_svc.list_all(limit=200)
        if channel.provider == ChannelProvider.google_ads
        and channel.status == ChannelStatus.connected
    ]

    history_rows: list[dict[str, object]] = []
    errors: list[str] = []

    if cred_svc is None:
        errors.append(
            "Encryption key is not configured, so Google Ads credentials cannot be read."
        )
    else:
        for channel in channels:
            if not channel.credentials_encrypted:
                continue
            creds = cred_svc.decrypt(channel.credentials_encrypted)
            if not creds:
                errors.append(f"Could not decrypt credentials for {channel.name}.")
                continue
            try:
                adapter = get_adapter(
                    ChannelProvider.google_ads,
                    access_token=creds.get("access_token", ""),
                    customer_id=creds.get("customer_id")
                    or channel.external_account_id
                    or "",
                    developer_token=creds.get("developer_token", ""),
                )
                rows = await adapter.fetch_ads_history(start_date, end_date)
            except (ValueError, RuntimeError) as exc:
                logger.error(
                    "Google Ads page fetch failed for %s: %s", channel.name, exc
                )
                errors.append(f"Could not load Google Ads history for {channel.name}.")
                continue

            for row in rows:
                history_rows.append(
                    {
                        **row,
                        "channel_name": channel.name,
                        "customer_id": channel.external_account_id or "",
                    }
                )

    history_rows = _coalesce_history_rows(
        history_rows,
        key_fields=(
            "customer_id",
            "date_start",
            "campaign_id",
            "ad_group_id",
            "ad_id",
        ),
        metric_fields=("impressions", "clicks", "spend", "conversions"),
    )
    history_rows.sort(
        key=lambda item: (
            str(item.get("date_start", "")),
            str(item.get("campaign_name", "")),
            str(item.get("ad_name", "")),
        ),
        reverse=True,
    )
    return history_rows, errors, channels


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
            post_id=selected_post_id,
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
    chart_channel_metrics = AnalyticsChartService.prepare_chart_channel_metrics(
        visual_channel_metrics, active_metric_keys
    )
    time_series_chart = AnalyticsChartService.build_time_series_chart(
        daily_metric_breakdown, active_metric_keys
    )
    channel_strengths = AnalyticsChartService.build_channel_strengths(
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


@router.get("/meta-ads", response_class=HTMLResponse)
async def meta_ads_analytics(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    campaign: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Detailed Meta Ads history across connected Meta ad accounts."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    history_rows, errors, channels = await _load_meta_ads_history(db, d_start, d_end)
    campaign_options = sorted(
        {
            (
                str(row.get("campaign_id", "") or ""),
                str(row.get("campaign_name", "") or "Unlabeled campaign"),
            )
            for row in history_rows
        },
        key=lambda item: item[1].lower(),
    )
    history_rows = _filter_meta_ads_rows(history_rows, campaign)
    totals = _meta_ads_summary(history_rows)
    currency_code = _resolve_currency_code(history_rows, default="NGN")
    currency_prefix = _currency_prefix(currency_code)

    campaign_totals: dict[tuple[str, str], dict[str, float | str]] = {}
    for row in history_rows:
        key = (str(row.get("channel_name", "")), str(row.get("campaign_name", "")))
        if key not in campaign_totals:
            campaign_totals[key] = {
                "channel_name": key[0],
                "campaign_name": key[1] or "Unlabeled campaign",
                "impressions": 0.0,
                "reach": 0.0,
                "clicks": 0.0,
                "spend": 0.0,
                "conversions": 0.0,
            }
        for metric in ("impressions", "reach", "clicks", "spend", "conversions"):
            campaign_totals[key][metric] = float(campaign_totals[key][metric]) + float(
                row.get(metric, 0) or 0
            )
        campaign_totals[key]["account_currency"] = currency_code

    account_totals: dict[tuple[str, str], dict[str, float | str]] = {}
    for row in history_rows:
        key = (str(row.get("channel_name", "")), str(row.get("account_id", "")))
        if key not in account_totals:
            account_totals[key] = {
                "channel_name": key[0],
                "account_id": key[1],
                "impressions": 0.0,
                "reach": 0.0,
                "clicks": 0.0,
                "spend": 0.0,
                "conversions": 0.0,
            }
        for metric in ("impressions", "reach", "clicks", "spend", "conversions"):
            account_totals[key][metric] = float(account_totals[key][metric]) + float(
                row.get(metric, 0) or 0
            )
        account_totals[key]["account_currency"] = currency_code

    page_size = 50
    total_rows = len(history_rows)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    current_page = min(max(page, 1), total_pages)
    start_index = (current_page - 1) * page_size
    paginated_history_rows = history_rows[start_index : start_index + page_size]

    ctx = {
        "request": request,
        "title": "Meta Ads",
        "page_title": "Meta Ads",
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
        "today_iso": today.isoformat(),
        "selected_campaign": campaign or "",
        "campaign_options": [
            {"value": campaign_id or campaign_name, "label": campaign_name}
            for campaign_id, campaign_name in campaign_options
        ],
        "channels": channels,
        "errors": errors,
        "history_rows": paginated_history_rows,
        "account_rows": sorted(
            account_totals.values(),
            key=lambda item: (str(item["channel_name"]), str(item["account_id"])),
        ),
        "campaign_rows": sorted(
            campaign_totals.values(),
            key=lambda item: float(item["spend"]),
            reverse=True,
        ),
        "total_impressions": int(totals["impressions"]),
        "total_reach": int(totals["reach"]),
        "total_clicks": int(totals["clicks"]),
        "total_spend": float(totals["spend"]),
        "total_conversions": float(totals["conversions"]),
        "currency_code": currency_code,
        "currency_prefix": currency_prefix,
        "page": current_page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": total_pages,
        "has_prev_page": current_page > 1,
        "has_next_page": current_page < total_pages,
        "prev_page": current_page - 1,
        "next_page": current_page + 1,
    }
    return templates.TemplateResponse("analytics/meta_ads.html", ctx)


@router.get("/meta-ads/export")
async def export_meta_ads_csv(
    start_date: str | None = None,
    end_date: str | None = None,
    campaign: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> StreamingResponse:
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)
    history_rows, _, _ = await _load_meta_ads_history(db, d_start, d_end)
    history_rows = _filter_meta_ads_rows(history_rows, campaign)
    export_rows = [
        {
            "date_start": row.get("date_start", ""),
            "channel_name": row.get("channel_name", ""),
            "account_id": row.get("account_id", ""),
            "account_currency": row.get("account_currency", ""),
            "campaign_name": row.get("campaign_name", ""),
            "campaign_id": row.get("campaign_id", ""),
            "adset_name": row.get("adset_name", ""),
            "adset_id": row.get("adset_id", ""),
            "ad_name": row.get("ad_name", ""),
            "ad_id": row.get("ad_id", ""),
            "impressions": int(float(row.get("impressions", 0) or 0)),
            "reach": int(float(row.get("reach", 0) or 0)),
            "clicks": int(float(row.get("clicks", 0) or 0)),
            "ctr": round(float(row.get("ctr", 0) or 0), 2),
            "spend": round(float(row.get("spend", 0) or 0), 2),
            "conversions": round(float(row.get("conversions", 0) or 0), 2),
        }
        for row in history_rows
    ]
    return _csv_response(
        f"meta_ads_{d_start}_{d_end}.csv",
        [
            "date_start",
            "channel_name",
            "account_id",
            "account_currency",
            "campaign_name",
            "campaign_id",
            "adset_name",
            "adset_id",
            "ad_name",
            "ad_id",
            "impressions",
            "reach",
            "clicks",
            "ctr",
            "spend",
            "conversions",
        ],
        export_rows,
    )


@router.get("/google-ads", response_class=HTMLResponse)
async def google_ads_analytics(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Detailed Google Ads history across connected customer accounts."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    history_rows, errors, channels = await _load_google_ads_history(db, d_start, d_end)
    totals = _ads_summary(history_rows)

    campaign_totals: dict[tuple[str, str], dict[str, float | str]] = {}
    for row in history_rows:
        key = (str(row.get("channel_name", "")), str(row.get("campaign_name", "")))
        if key not in campaign_totals:
            campaign_totals[key] = {
                "channel_name": key[0],
                "campaign_name": key[1] or "Unlabeled campaign",
                "impressions": 0.0,
                "clicks": 0.0,
                "spend": 0.0,
                "conversions": 0.0,
            }
        for metric in ("impressions", "clicks", "spend", "conversions"):
            campaign_totals[key][metric] = float(campaign_totals[key][metric]) + float(
                row.get(metric, 0) or 0
            )

    ctx = {
        "request": request,
        "title": "Google Ads",
        "page_title": "Google Ads",
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
        "today_iso": today.isoformat(),
        "channels": channels,
        "errors": errors,
        "history_rows": history_rows,
        "campaign_rows": sorted(
            campaign_totals.values(),
            key=lambda item: float(item["spend"]),
            reverse=True,
        ),
        "total_impressions": int(totals["impressions"]),
        "total_clicks": int(totals["clicks"]),
        "total_spend": float(totals["spend"]),
        "total_conversions": float(totals["conversions"]),
    }
    return templates.TemplateResponse("analytics/google_ads.html", ctx)


@router.get("/google-ads/export")
async def export_google_ads_csv(
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> StreamingResponse:
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)
    history_rows, _, _ = await _load_google_ads_history(db, d_start, d_end)
    export_rows = [
        {
            "date_start": row.get("date_start", ""),
            "channel_name": row.get("channel_name", ""),
            "customer_id": row.get("customer_id", ""),
            "campaign_name": row.get("campaign_name", ""),
            "campaign_id": row.get("campaign_id", ""),
            "ad_group_name": row.get("ad_group_name", ""),
            "ad_group_id": row.get("ad_group_id", ""),
            "ad_name": row.get("ad_name", ""),
            "ad_id": row.get("ad_id", ""),
            "impressions": int(float(row.get("impressions", 0) or 0)),
            "clicks": int(float(row.get("clicks", 0) or 0)),
            "ctr": round(float(row.get("ctr", 0) or 0), 2),
            "average_cpc": round(float(row.get("average_cpc", 0) or 0), 2),
            "spend": round(float(row.get("spend", 0) or 0), 2),
            "conversions": round(float(row.get("conversions", 0) or 0), 2),
        }
        for row in history_rows
    ]
    return _csv_response(
        f"google_ads_{d_start}_{d_end}.csv",
        [
            "date_start",
            "channel_name",
            "customer_id",
            "campaign_name",
            "campaign_id",
            "ad_group_name",
            "ad_group_id",
            "ad_name",
            "ad_id",
            "impressions",
            "clicks",
            "ctr",
            "average_cpc",
            "spend",
            "conversions",
        ],
        export_rows,
    )


@router.get("/export")
def export_metrics_csv(
    start_date: str | None = None,
    end_date: str | None = None,
    metric_date: str | None = None,
    post_id: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> StreamingResponse:
    """Export analytics metrics as CSV for a date range."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)
    d_metric = _parse_date(metric_date, d_end) if metric_date else None
    selected_post_id = _parse_uuid(post_id)

    chart_svc = AnalyticsChartService(db)
    csv_content = chart_svc.export_csv(
        start_date=d_start,
        end_date=d_end,
        metric_date=d_metric,
        post_id=selected_post_id,
    )
    filename = f"analytics_{d_start}_{d_end}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Unified Ads Dashboard ───────────────────────────────────────────────────

PLATFORM_DISPLAY = {
    "meta": "Meta Ads",
    "google": "Google Ads",
    "linkedin": "LinkedIn Ads",
}


@router.get("/ads", response_class=HTMLResponse)
def ads_dashboard(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    platform: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Unified ads dashboard across all platforms, reading from local DB."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    platform_filter: AdPlatform | None = None
    if platform:
        with contextlib.suppress(ValueError):
            platform_filter = AdPlatform(platform)

    ad_svc = AdDashboardService(db)
    overview = ad_svc.get_overview(start_date=d_start, end_date=d_end)
    platform_summary = ad_svc.get_platform_summary(start_date=d_start, end_date=d_end)
    campaigns = ad_svc.get_campaigns(
        platform=platform_filter, start_date=d_start, end_date=d_end
    )
    daily_totals = ad_svc.get_daily_totals(
        platform=platform_filter, start_date=d_start, end_date=d_end
    )

    # Enrich platform display names
    for ps in platform_summary:
        ps["display_name"] = PLATFORM_DISPLAY.get(ps["platform"], ps["platform"])
    for c in campaigns:
        c["platform_display"] = PLATFORM_DISPLAY.get(c["platform"], c["platform"])

    ctx = {
        "request": request,
        "title": "All Ads",
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
        "today_iso": today.isoformat(),
        "selected_platform": platform or "",
        "platforms": [
            {"value": p.value, "label": PLATFORM_DISPLAY.get(p.value, p.value)}
            for p in AdPlatform
        ],
        "overview": overview,
        "platform_summary": platform_summary,
        "campaigns": campaigns,
        "daily_totals": daily_totals,
    }
    return templates.TemplateResponse("analytics/ads_dashboard.html", ctx)


@router.get("/ads/{ad_campaign_id}", response_class=HTMLResponse)
def ad_campaign_detail(
    request: Request,
    ad_campaign_id: UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Drill-down into a single ad campaign."""
    today = date.today()
    d_start = _parse_date(start_date, today - timedelta(days=30))
    d_end = _parse_date(end_date, today)

    ad_svc = AdDashboardService(db)
    detail = ad_svc.get_campaign_detail(
        ad_campaign_id, start_date=d_start, end_date=d_end
    )
    if detail is None:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(
            url="/analytics/ads?error=Ad+campaign+not+found", status_code=302
        )

    detail["campaign"]["platform_display"] = PLATFORM_DISPLAY.get(
        detail["campaign"]["platform"], detail["campaign"]["platform"]
    )

    ctx = {
        "request": request,
        "title": f"Ad Campaign — {detail['campaign']['name']}",
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
        "detail": detail,
    }
    return templates.TemplateResponse("analytics/ad_campaign_detail.html", ctx)


@router.post("/ads/{ad_campaign_id}/link", response_model=None)
async def link_ad_campaign(
    request: Request,
    ad_campaign_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Link or unlink an ad campaign to an internal Campaign."""
    from fastapi.responses import RedirectResponse

    form = await request.form()
    campaign_id = _parse_uuid(str(form.get("campaign_id", "")).strip())

    ad_svc = AdDashboardService(db)
    try:
        ad_svc.link_to_campaign(ad_campaign_id, campaign_id)
        db.commit()
    except ValueError:
        return RedirectResponse(
            url="/analytics/ads?error=Ad+campaign+not+found", status_code=302
        )

    return RedirectResponse(
        url=f"/analytics/ads/{ad_campaign_id}?success=Link+updated", status_code=302
    )
