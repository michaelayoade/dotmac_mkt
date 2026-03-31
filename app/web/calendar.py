"""Calendar view for scheduled posts plus CSV import/export."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from json import JSONDecodeError
from urllib.parse import quote_plus
from uuid import UUID

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.campaign import Campaign
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.models.post import Post, PostStatus
from app.schemas.post import PostCreate, PostUpdate
from app.services.calendar_service import CalendarService
from app.services.campaign_service import CampaignService
from app.services.channel_service import ChannelService
from app.services.post_service import PostService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["web-calendar"])

CSV_HEADERS = [
    "post_id",
    "campaign_name",
    "campaign_id",
    "title",
    "content",
    "status",
    "scheduled_at",
    "channels",
    "channel_ids",
    "channel_overrides_json",
]
IMPORTABLE_PROVIDERS = {
    ChannelProvider.meta_instagram,
    ChannelProvider.meta_facebook,
    ChannelProvider.twitter,
    ChannelProvider.linkedin,
}


def _clean_cell(value: str | None) -> str:
    return (value or "").strip()


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _parse_pipe_separated(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def _parse_scheduled_at(value: str, *, row_num: int) -> datetime | None:
    cleaned = _clean_cell(value)
    if not cleaned:
        return None
    normalized = cleaned.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Row {row_num}: scheduled_at must be ISO-8601, for example 2026-04-10T09:00:00Z."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _parse_status(value: str, *, row_num: int) -> PostStatus:
    cleaned = _clean_cell(value) or PostStatus.draft.value
    try:
        return PostStatus(cleaned)
    except ValueError as exc:
        allowed = ", ".join(status.value for status in PostStatus)
        raise ValueError(f"Row {row_num}: status must be one of {allowed}.") from exc


def _connected_channels(db: Session) -> list[Channel]:
    stmt = (
        select(Channel)
        .where(Channel.status == ChannelStatus.connected)
        .where(Channel.provider.in_(IMPORTABLE_PROVIDERS))
        .order_by(Channel.name)
    )
    return list(db.scalars(stmt).all())


def _campaign_lookup(
    campaigns: Iterable[Campaign],
) -> tuple[dict[str, Campaign], dict[str, Campaign]]:
    by_id: dict[str, Campaign] = {}
    by_name: dict[str, Campaign] = {}
    for campaign in campaigns:
        by_id[str(campaign.id)] = campaign
        normalized = _normalize_name(campaign.name)
        if normalized and normalized not in by_name:
            by_name[normalized] = campaign
    return by_id, by_name


def _channel_lookup(
    channels: Iterable[Channel],
) -> tuple[dict[str, Channel], dict[str, Channel]]:
    by_id: dict[str, Channel] = {}
    by_name: dict[str, Channel] = {}
    for channel in channels:
        by_id[str(channel.id)] = channel
        normalized = _normalize_name(channel.name)
        if normalized and normalized not in by_name:
            by_name[normalized] = channel
    return by_id, by_name


def _resolve_campaign(
    row: dict[str, str],
    *,
    row_num: int,
    campaigns_by_id: dict[str, Campaign],
    campaigns_by_name: dict[str, Campaign],
) -> Campaign:
    campaign_id = _clean_cell(row.get("campaign_id"))
    campaign_name = _clean_cell(row.get("campaign_name"))
    if campaign_id and campaign_id in campaigns_by_id:
        return campaigns_by_id[campaign_id]
    if campaign_name:
        campaign = campaigns_by_name.get(_normalize_name(campaign_name))
        if campaign is not None:
            return campaign
    raise ValueError(
        f"Row {row_num}: campaign not found. Provide an existing campaign_id or campaign_name."
    )


def _resolve_channels(
    row: dict[str, str],
    *,
    row_num: int,
    channels_by_id: dict[str, Channel],
    channels_by_name: dict[str, Channel],
) -> list[Channel]:
    selected: list[Channel] = []
    seen: set[UUID] = set()
    for channel_id in _parse_pipe_separated(_clean_cell(row.get("channel_ids"))):
        channel = channels_by_id.get(channel_id)
        if channel is None:
            raise ValueError(f"Row {row_num}: unknown channel_id '{channel_id}'.")
        if channel.id not in seen:
            selected.append(channel)
            seen.add(channel.id)
    for channel_name in _parse_pipe_separated(_clean_cell(row.get("channels"))):
        channel = channels_by_name.get(_normalize_name(channel_name))
        if channel is None:
            raise ValueError(
                f"Row {row_num}: unknown channel '{channel_name}'. Use the export file as the template."
            )
        if channel.id not in seen:
            selected.append(channel)
            seen.add(channel.id)
    return selected


def _parse_overrides(
    row: dict[str, str],
    *,
    row_num: int,
    selected_channels: list[Channel],
) -> dict[UUID, str]:
    raw = _clean_cell(row.get("channel_overrides_json"))
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except JSONDecodeError as exc:
        raise ValueError(
            f"Row {row_num}: channel_overrides_json must be valid JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Row {row_num}: channel_overrides_json must be a JSON object keyed by channel name or id."
        )
    overrides: dict[UUID, str] = {}
    by_id = {str(channel.id): channel for channel in selected_channels}
    by_name = {_normalize_name(channel.name): channel for channel in selected_channels}
    for raw_key, raw_value in parsed.items():
        key = _clean_cell(str(raw_key))
        value = _clean_cell(str(raw_value))
        if not key or not value:
            continue
        channel = by_id.get(key) or by_name.get(_normalize_name(key))
        if channel is None:
            raise ValueError(
                f"Row {row_num}: override key '{key}' does not match a selected channel."
            )
        overrides[channel.id] = value
    return overrides


def _serialize_post_row(post: Post) -> dict[str, str]:
    deliveries = list(post.deliveries)
    channels = [
        delivery.channel for delivery in deliveries if delivery.channel is not None
    ]
    if not channels and post.channel is not None:
        channels = [post.channel]
    overrides = {
        delivery.channel.name: delivery.content_override or ""
        for delivery in deliveries
        if delivery.channel is not None and (delivery.content_override or "").strip()
    }
    scheduled_at = ""
    if post.scheduled_at is not None:
        scheduled_dt = post.scheduled_at
        if scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace(tzinfo=UTC)
        scheduled_at = scheduled_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "post_id": str(post.id),
        "campaign_name": post.campaign.name if post.campaign else "",
        "campaign_id": str(post.campaign_id),
        "title": post.title or "",
        "content": post.content or "",
        "status": post.status.value if post.status else PostStatus.draft.value,
        "scheduled_at": scheduled_at,
        "channels": "|".join(channel.name for channel in channels),
        "channel_ids": "|".join(str(channel.id) for channel in channels),
        "channel_overrides_json": json.dumps(overrides, ensure_ascii=True),
    }


def _example_rows(
    campaigns: list[Campaign], channels: list[Channel]
) -> list[dict[str, str]]:
    if not campaigns:
        return [
            {
                "post_id": "",
                "campaign_name": "Create a campaign first",
                "campaign_id": "",
                "title": "April launch teaser",
                "content": "Short teaser copy for the launch campaign.",
                "status": "planned",
                "scheduled_at": "2026-04-10T09:00:00Z",
                "channels": "Twitter|LinkedIn",
                "channel_ids": "",
                "channel_overrides_json": '{"Twitter": "Shorter teaser for X"}',
            }
        ]
    campaign = campaigns[0]
    selected_channels = channels[:2]
    channel_names = "|".join(channel.name for channel in selected_channels)
    channel_ids = "|".join(str(channel.id) for channel in selected_channels)
    overrides_json = "{}"
    if selected_channels:
        overrides_json = json.dumps(
            {selected_channels[0].name: "Shorter platform-specific copy."},
            ensure_ascii=True,
        )
    return [
        {
            "post_id": "",
            "campaign_name": campaign.name,
            "campaign_id": str(campaign.id),
            "title": "April launch teaser",
            "content": "Short teaser copy for the launch campaign.",
            "status": "planned",
            "scheduled_at": "2026-04-10T09:00:00Z",
            "channels": channel_names,
            "channel_ids": channel_ids,
            "channel_overrides_json": overrides_json,
        }
    ]


def _csv_response(filename: str, rows: list[dict[str, str]]) -> Response:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=CSV_HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    }
    return templates.TemplateResponse("calendar/index.html", ctx)


@router.get("/export.csv")
def export_calendar_csv(
    campaign_id: UUID | None = None,
    channel_id: UUID | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    _ = auth
    posts = PostService(db).list_all(
        campaign_id=campaign_id,
        channel_id=channel_id,
        limit=5000,
        offset=0,
    )
    rows = [_serialize_post_row(post) for post in posts]
    return _csv_response("content-calendar-export.csv", rows)


@router.get("/import/example.csv")
def export_calendar_example_csv(
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    _ = auth
    campaigns = CampaignService(db).list_all(limit=100)
    channels = _connected_channels(db)
    return _csv_response(
        "content-calendar-example.csv",
        _example_rows(campaigns, channels),
    )


@router.post("/import", response_model=None)
async def import_calendar_csv(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    form = await request.form()
    _ = form.get("csrf_token")
    uploaded_file: UploadFile | None = form.get("file")  # type: ignore[assignment]

    if uploaded_file is None or not uploaded_file.filename:
        return RedirectResponse(
            url="/calendar?error=Please+select+a+CSV+file+to+import",
            status_code=302,
        )

    try:
        raw = await uploaded_file.read()
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("The uploaded CSV is empty.")
        missing_headers = [
            header for header in CSV_HEADERS if header not in reader.fieldnames
        ]
        if missing_headers:
            raise ValueError("Missing required columns: " + ", ".join(missing_headers))

        campaigns = CampaignService(db).list_all(limit=500)
        channels = _connected_channels(db)
        campaigns_by_id, campaigns_by_name = _campaign_lookup(campaigns)
        channels_by_id, channels_by_name = _channel_lookup(channels)
        post_svc = PostService(db)
        actor_id = UUID(auth["person_id"])

        created_count = 0
        updated_count = 0

        for row_num, row in enumerate(reader, start=2):
            if not any(
                _clean_cell(str(value)) for value in row.values() if value is not None
            ):
                continue

            campaign = _resolve_campaign(
                row,
                row_num=row_num,
                campaigns_by_id=campaigns_by_id,
                campaigns_by_name=campaigns_by_name,
            )
            selected_channels = _resolve_channels(
                row,
                row_num=row_num,
                channels_by_id=channels_by_id,
                channels_by_name=channels_by_name,
            )
            channel_ids = [channel.id for channel in selected_channels]
            overrides = _parse_overrides(
                row,
                row_num=row_num,
                selected_channels=selected_channels,
            )
            status = _parse_status(row.get("status", ""), row_num=row_num)
            scheduled_at = _parse_scheduled_at(
                row.get("scheduled_at", ""),
                row_num=row_num,
            )
            title = _clean_cell(row.get("title"))
            if not title:
                raise ValueError(f"Row {row_num}: title is required.")
            content = _clean_cell(row.get("content")) or None
            post_id_raw = _clean_cell(row.get("post_id"))

            if post_id_raw:
                try:
                    existing_id = UUID(post_id_raw)
                except ValueError as exc:
                    raise ValueError(
                        f"Row {row_num}: post_id '{post_id_raw}' is not a valid UUID."
                    ) from exc
                existing = post_svc.get_by_id(existing_id)
                if existing is None:
                    raise ValueError(
                        f"Row {row_num}: post_id '{post_id_raw}' was provided but no matching post exists."
                    )
                if existing.campaign_id != campaign.id:
                    raise ValueError(
                        f"Row {row_num}: post_id belongs to a different campaign."
                    )
                post_svc.update(
                    existing.id,
                    PostUpdate(
                        title=title,
                        content=content,
                        status=status,
                        channel_id=channel_ids[0] if channel_ids else None,
                        scheduled_at=scheduled_at,
                    ),
                )
                post_svc.replace_deliveries(
                    existing,
                    channel_ids=channel_ids,
                    content=content,
                    content_overrides=overrides,
                )
                updated_count += 1
                continue

            created = post_svc.create(
                PostCreate(
                    title=title,
                    content=content,
                    status=status,
                    campaign_id=campaign.id,
                    channel_id=channel_ids[0] if channel_ids else None,
                    channel_ids=channel_ids,
                    scheduled_at=scheduled_at,
                ),
                created_by=actor_id,
            )
            post_svc.replace_deliveries(
                created,
                channel_ids=channel_ids,
                content=content,
                content_overrides=overrides,
            )
            created_count += 1

        db.commit()
        success_message = f"Imported {created_count} new posts and updated {updated_count} existing posts"
        return RedirectResponse(
            url=f"/calendar?success={quote_plus(success_message)}",
            status_code=302,
        )
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            url=f"/calendar?error={quote_plus(str(exc))}",
            status_code=302,
        )
    except UnicodeDecodeError:
        db.rollback()
        return RedirectResponse(
            url="/calendar?error=CSV+files+must+be+UTF-8+encoded",
            status_code=302,
        )
    except Exception as exc:
        logger.exception("Calendar import failed: %s", exc)
        db.rollback()
        return RedirectResponse(
            url="/calendar?error=Calendar+import+failed",
            status_code=302,
        )
