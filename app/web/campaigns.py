"""Campaign management web routes."""

from __future__ import annotations

import contextlib
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.responses import Response

from app.api.deps import get_db
from app.models.campaign import Campaign, CampaignStatus, campaign_members
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.models.post import Post, PostStatus
from app.models.post_delivery import PostDelivery
from app.models.task import Task
from app.schemas.campaign import CampaignCreate, CampaignUpdate
from app.schemas.post import PostCreate, PostUpdate
from app.services.analytics_service import AnalyticsService
from app.services.asset_service import AssetService
from app.services.campaign_service import CampaignService
from app.services.post_asset_service import PostAssetService
from app.services.post_service import PostService, post_recency_sort_expr
from app.services.publishing_service import PublishingService
from app.services.task_service import MktTaskService
from app.tasks.analytics_sync import (
    sync_post_metrics_now,
    sync_recent_channel_posts_now,
)
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["web-campaigns"])

PAGE_SIZE = 25

# Channel providers that support publish_post()
PUBLISHABLE_PROVIDERS = {
    ChannelProvider.meta_instagram,
    ChannelProvider.meta_facebook,
    ChannelProvider.twitter,
    ChannelProvider.linkedin,
}

PLATFORM_LIMITS: dict[ChannelProvider, int] = {
    ChannelProvider.twitter: 280,
    ChannelProvider.linkedin: 3000,
    ChannelProvider.meta_instagram: 2200,
    ChannelProvider.meta_facebook: 63206,
}


_POST_DELIVERIES_TABLE_PRESENT: bool | None = None


def _has_post_deliveries_table(db: Session) -> bool:
    global _POST_DELIVERIES_TABLE_PRESENT
    if _POST_DELIVERIES_TABLE_PRESENT is None:
        bind = db.get_bind()
        _POST_DELIVERIES_TABLE_PRESENT = bool(
            bind is not None and sa_inspect(bind).has_table("post_deliveries")
        )
    return _POST_DELIVERIES_TABLE_PRESENT


def _safe_deliveries(db: Session, post: Post | None) -> list[PostDelivery]:
    if post is None or not _has_post_deliveries_table(db):
        return []
    return list(post.deliveries)


def _selected_channels(db: Session, post: Post | None) -> list[Channel]:
    if post is None:
        return []
    deliveries = _safe_deliveries(db, post)
    if deliveries:
        return [delivery.channel for delivery in deliveries if delivery.channel]
    return [post.channel] if post.channel else []


def _channel_selection_and_warnings(
    channels: list[Channel],
    content: str,
    selected_ids: list[UUID],
    content_overrides: dict[UUID, str] | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    selected_set = set(selected_ids)
    overrides = content_overrides or {}
    options: list[dict[str, object]] = []
    warnings: list[str] = []
    for channel in channels:
        override = (overrides.get(channel.id) or "").strip()
        effective_content = override or (content or "").strip()
        content_length = len(effective_content)
        limit = PLATFORM_LIMITS.get(channel.provider)
        options.append(
            {
                "id": str(channel.id),
                "name": channel.name,
                "provider": channel.provider.value,
                "selected": channel.id in selected_set,
                "override": override,
                "limit": limit,
            }
        )
        if channel.id in selected_set and limit is not None and content_length > limit:
            source = "override" if override else "base content"
            warnings.append(
                f"{channel.name} {source} exceeds the recommended limit of {limit} characters."
            )
    return options, warnings


def _parse_channel_ids(form) -> list[UUID]:
    channel_ids_raw = form.getlist("channel_ids") or []
    channel_ids: list[UUID] = []
    for value in channel_ids_raw:
        with contextlib.suppress(ValueError, TypeError):
            channel_ids.append(UUID(str(value)))
    if not channel_ids:
        channel_id_str = str(form.get("channel_id", ""))
        with contextlib.suppress(ValueError, TypeError):
            if channel_id_str:
                channel_ids = [UUID(channel_id_str)]
    return channel_ids


def _parse_content_overrides(form, channel_ids: list[UUID]) -> dict[UUID, str]:
    overrides: dict[UUID, str] = {}
    for channel_id in channel_ids:
        raw_value = str(form.get(f"override_{channel_id}", "") or "")
        cleaned = raw_value.strip()
        if cleaned:
            overrides[channel_id] = cleaned
    return overrides


def _delivery_override_map(db: Session, post: Post | None) -> dict[str, str]:
    if post is None:
        return {}
    return {
        str(delivery.channel_id): delivery.content_override or ""
        for delivery in _safe_deliveries(db, post)
        if delivery.channel_id
    }


def _delivery_rows(db: Session, post: Post | None) -> list[dict[str, str | bool]]:
    if post is None:
        return []
    rows: list[dict[str, str | bool]] = []
    for delivery in sorted(
        _safe_deliveries(db, post),
        key=lambda item: (
            item.channel.name.lower() if item.channel else "",
            item.provider.value if item.provider else "",
        ),
    ):
        provider_value = delivery.provider.value if delivery.provider else "unknown"
        channel_name = delivery.channel.name if delivery.channel else provider_value
        rows.append(
            {
                "channel_name": channel_name,
                "provider": provider_value.replace("_", " ").title(),
                "status": (
                    delivery.status.value if delivery.status is not None else "unknown"
                ),
                "external_post_id": delivery.external_post_id or "Not linked",
                "published_at": (
                    delivery.published_at.strftime("%b %d, %Y %H:%M")
                    if delivery.published_at
                    else "Not published yet"
                ),
                "error_message": delivery.error_message or "",
                "has_override": bool((delivery.content_override or "").strip()),
            }
        )
    return rows


def _post_form_asset_urls(
    campaign_id: UUID, post_id: UUID | None = None
) -> dict[str, str]:
    return {
        "asset_create_url": (
            f"/assets/create?campaign_id={campaign_id}"
            f"&next=/campaigns/{campaign_id}/posts/{post_id}/edit"
            if post_id is not None
            else f"/assets/create?campaign_id={campaign_id}&next=/campaigns/{campaign_id}/posts/create"
        ),
        "asset_manage_url": f"/assets?campaign_id={campaign_id}",
    }


def _can_edit_campaign(db: Session, campaign: Campaign, person_id: UUID) -> bool:
    """Check if a person is the creator or a member of the campaign."""
    if campaign.created_by == person_id:
        return True
    member = db.execute(
        select(campaign_members.c.person_id)
        .where(campaign_members.c.campaign_id == campaign.id)
        .where(campaign_members.c.person_id == person_id)
    ).first()
    return member is not None


def _campaign_metric_window(campaign: Campaign) -> tuple[date, date]:
    today = date.today()
    start_date = campaign.start_date or (today - timedelta(days=30))
    end_date = campaign.end_date or today
    if end_date < start_date:
        end_date = start_date
    return start_date, end_date


def _post_action_capabilities(db: Session, post: Post | None) -> dict[str, str | bool]:
    if post is None:
        return {
            "can_edit_post": False,
            "edit_block_reason": "",
            "can_delete_post": False,
            "delete_block_reason": "",
        }

    deliveries = _safe_deliveries(db, post)
    channel = post.channel
    can_edit_post = True
    edit_block_reason = ""
    can_delete_post = True
    delete_block_reason = ""

    if post.status == PostStatus.published:
        if len(deliveries) > 1:
            return {
                "can_edit_post": False,
                "edit_block_reason": "Cross-platform published posts cannot be edited in one action yet.",
                "can_delete_post": False,
                "delete_block_reason": "Cross-platform published posts cannot be deleted in one action yet.",
            }
        if len(deliveries) == 1 and deliveries[0].channel is not None:
            channel = deliveries[0].channel
        can_edit_post = PublishingService.supports_remote_update(channel)
        can_delete_post = PublishingService.supports_remote_delete(channel)
        if not can_edit_post:
            edit_block_reason = "This channel does not support remote post edits."
        if not can_delete_post:
            delete_block_reason = "This channel does not support remote post deletion."

    return {
        "can_edit_post": can_edit_post,
        "edit_block_reason": edit_block_reason,
        "can_delete_post": can_delete_post,
        "delete_block_reason": delete_block_reason,
    }


def _decorate_posts_with_action_capabilities(posts: list[Post]) -> list[Post]:
    for post in posts:
        db = Session.object_session(post)
        if db is None:
            continue
        selected_channels = _selected_channels(db, post)
        post.display_channel_name = (
            ", ".join(
                dict.fromkeys(
                    channel.name for channel in selected_channels if channel.name
                )
            )
            or "-"
        )
        for key, value in _post_action_capabilities(db, post).items():
            setattr(post, key, value)
    return posts


def _build_post_detail_ctx(
    db: Session,
    *,
    campaign: Campaign,
    post: Post | None,
) -> dict:
    if post is None:
        return {
            "selected_post": None,
            "metric_cards": [],
            "daily_rows": [],
            "views_label": "Views / Reach",
            "can_publish_now": False,
            "publish_block_reason": "",
        }

    analytics_svc = AnalyticsService(db)
    start_date, end_date = _campaign_metric_window(campaign)
    overview = analytics_svc.get_overview(
        start_date=start_date,
        end_date=end_date,
        post_id=post.id,
    )
    daily_rows = analytics_svc.get_daily_totals(
        start_date=start_date,
        end_date=end_date,
        post_id=post.id,
    )
    if (
        post.status == PostStatus.published
        and post.external_post_id
        and not overview
        and not daily_rows
    ):
        sync_post_metrics_now(post, db)
        db.flush()
        overview = analytics_svc.get_overview(
            start_date=start_date,
            end_date=end_date,
            post_id=post.id,
        )
        daily_rows = analytics_svc.get_daily_totals(
            start_date=start_date,
            end_date=end_date,
            post_id=post.id,
        )

    impressions = int(round(overview.get("impressions", 0.0)))
    pageviews = int(round(overview.get("pageviews", 0.0)))
    reach = int(round(overview.get("reach", 0.0)))
    engagement = int(round(overview.get("engagement", 0.0)))

    publish_block_reason = ""
    can_publish_now = True
    action_capabilities = _post_action_capabilities(db, post)
    can_edit_post = bool(action_capabilities["can_edit_post"])
    edit_block_reason = str(action_capabilities["edit_block_reason"])
    can_delete_post = bool(action_capabilities["can_delete_post"])
    delete_block_reason = str(action_capabilities["delete_block_reason"])
    selected_channels = _selected_channels(db, post)
    if post.status == PostStatus.published:
        can_publish_now = False
        publish_block_reason = "This post has already been published."
    elif not selected_channels:
        can_publish_now = False
        publish_block_reason = "Select at least one channel before publishing."
    else:
        issues = PublishingService(db).publishability_issues(post)
        if issues:
            can_publish_now = False
            publish_block_reason = "; ".join(issues.values())

    return {
        "selected_post": post,
        "metric_cards": [
            {
                "label": "Impressions",
                "value": impressions,
                "tone": "text-sky-600 dark:text-sky-400",
                "bg": "bg-sky-50 dark:bg-sky-950/40",
            },
            {
                "label": "Views / Reach",
                "value": pageviews or reach,
                "tone": "text-violet-600 dark:text-violet-400",
                "bg": "bg-violet-50 dark:bg-violet-950/40",
            },
            {
                "label": "Engagement",
                "value": engagement,
                "tone": "text-emerald-600 dark:text-emerald-400",
                "bg": "bg-emerald-50 dark:bg-emerald-950/40",
            },
        ],
        "daily_rows": daily_rows[-7:][::-1],
        "views_label": "Views" if pageviews else "Reach",
        "can_publish_now": can_publish_now,
        "publish_block_reason": publish_block_reason,
        "can_edit_post": can_edit_post,
        "edit_block_reason": edit_block_reason,
        "can_delete_post": can_delete_post,
        "delete_block_reason": delete_block_reason,
        "selected_channels": selected_channels,
        "delivery_rows": _delivery_rows(db, post),
    }


@router.get("", response_class=HTMLResponse)
def list_campaigns(
    request: Request,
    page: int = 1,
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List campaigns with optional status filter and name search."""
    from sqlalchemy import func

    sync_recent_channel_posts_now(db)

    # Resolve status filter
    status_filter: CampaignStatus | None = None
    if status:
        with contextlib.suppress(ValueError):
            status_filter = CampaignStatus(status)

    # Build query for search support
    stmt = select(Campaign)
    if status_filter is not None:
        stmt = stmt.where(Campaign.status == status_filter)
    if q:
        stmt = stmt.where(Campaign.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Campaign.created_at.desc())

    # Count for pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    offset = (page - 1) * PAGE_SIZE
    items = list(db.scalars(stmt.offset(offset).limit(PAGE_SIZE)).all())

    # Batch fetch post/task counts in two queries instead of 2*N
    selected_campaign: Campaign | None = None
    selected_post: Post | None = None

    if items:
        campaign_ids = [c.id for c in items]

        post_counts = dict(
            db.execute(
                select(Post.campaign_id, func.count(Post.id))
                .where(Post.campaign_id.in_(campaign_ids))
                .group_by(Post.campaign_id)
            ).all()
        )
        task_counts = dict(
            db.execute(
                select(Task.campaign_id, func.count(Task.id))
                .where(Task.campaign_id.in_(campaign_ids))
                .group_by(Task.campaign_id)
            ).all()
        )

        for c in items:
            c.posts_count = post_counts.get(c.id, 0)
            c.tasks_count = task_counts.get(c.id, 0)

        preview_posts = list(
            db.scalars(
                select(Post)
                .where(Post.campaign_id.in_(campaign_ids))
                .options(
                    selectinload(Post.channel),
                    selectinload(Post.deliveries).selectinload(PostDelivery.channel),
                )
                .order_by(
                    Post.campaign_id,
                    post_recency_sort_expr().desc(),
                    Post.created_at.desc(),
                )
            ).all()
        )
        preview_posts_by_campaign: dict[UUID, list[Post]] = defaultdict(list)
        for post in preview_posts:
            bucket = preview_posts_by_campaign[post.campaign_id]
            if len(bucket) < 3:
                bucket.append(post)

        for c in items:
            c.posts_preview = _decorate_posts_with_action_capabilities(
                preview_posts_by_campaign.get(c.id, [])
            )
            c.posts_remaining = max(0, c.posts_count - len(c.posts_preview))

        for c in items:
            preview = c.posts_preview[0] if c.posts_preview else None
            if preview is not None:
                selected_campaign = c
                selected_post = preview
                break

    ctx = {
        "request": request,
        "title": "Campaigns",
        "campaigns": items,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "status_filter": status if status else "",
        "search_query": q if q else "",
        "statuses": [s.value for s in CampaignStatus],
    }
    if selected_campaign is not None and selected_post is not None:
        ctx.update(
            _build_post_detail_ctx(
                db,
                campaign=selected_campaign,
                post=selected_post,
            )
        )
        ctx["inspector_campaign"] = selected_campaign
        ctx["campaign"] = selected_campaign
    else:
        ctx.update(
            _build_post_detail_ctx(db, campaign=items[0], post=None) if items else {}
        )
        ctx["inspector_campaign"] = None
        ctx["campaign"] = None
    return templates.TemplateResponse("campaigns/list.html", ctx)


@router.get("/create", response_class=HTMLResponse)
def create_campaign_form(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render campaign creation form."""
    ctx = {
        "request": request,
        "title": "Create Campaign",
        "mode": "create",
        "statuses": [s.value for s in CampaignStatus],
    }
    return templates.TemplateResponse("campaigns/form.html", ctx)


@router.post("/create", response_model=None)
async def create_campaign_submit(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle campaign creation form submission."""
    form = await request.form()
    data = CampaignCreate(
        name=str(form.get("name", "")),
        description=str(form.get("description", "")) or None,
        status=CampaignStatus(str(form.get("status", "draft"))),
        start_date=str(form.get("start_date", "")) or None,
        end_date=str(form.get("end_date", "")) or None,
    )

    campaign_svc = CampaignService(db)
    record = campaign_svc.create(data, created_by=UUID(auth["person_id"]))
    db.commit()
    logger.info("Campaign created via web: %s", record.id)
    return RedirectResponse(url=f"/campaigns/{record.id}", status_code=302)


@router.get("/{id}", response_class=HTMLResponse)
def campaign_detail(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Campaign detail page with posts, tasks, and assets tabs."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )

    post_svc = PostService(db)
    all_posts = post_svc.list_all(campaign_id=id)
    total_posts = len(all_posts)
    published_posts = sum(1 for p in all_posts if p.status == PostStatus.published)
    progress_pct = round(published_posts / total_posts * 100) if total_posts > 0 else 0

    ctx = {
        "request": request,
        "title": record.name,
        "campaign": record,
        "total_posts": total_posts,
        "published_posts": published_posts,
        "progress_pct": progress_pct,
        "success_message": request.query_params.get("success", ""),
        "error_message": request.query_params.get("error", ""),
    }
    return templates.TemplateResponse("campaigns/detail.html", ctx)


@router.get("/{id}/tab/{tab}", response_class=HTMLResponse)
def campaign_tab(
    request: Request,
    id: UUID,
    tab: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Lazy-load a campaign detail tab via HTMX."""
    allowed_tabs = {"posts", "assets", "tasks", "analytics"}
    if tab not in allowed_tabs:
        return HTMLResponse(content="", status_code=404)

    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return HTMLResponse(
            content="<p class='text-sm text-red-500'>Campaign not found</p>",
            status_code=404,
        )

    ctx: dict = {"request": request, "campaign": record}

    if tab == "posts":
        post_svc = PostService(db)
        posts = _decorate_posts_with_action_capabilities(
            post_svc.list_all(campaign_id=id)
        )
        ctx["posts"] = posts
        ctx.update(
            _build_post_detail_ctx(
                db, campaign=record, post=posts[0] if posts else None
            )
        )
        return templates.TemplateResponse("campaigns/tabs/posts.html", ctx)
    elif tab == "assets":
        asset_svc = AssetService(db)
        ctx["assets"] = asset_svc.list_all(campaign_id=id)
        return templates.TemplateResponse("campaigns/tabs/assets.html", ctx)
    elif tab == "tasks":
        task_svc = MktTaskService(db)
        ctx["tasks"] = task_svc.list_all(campaign_id=id)
        return templates.TemplateResponse("campaigns/tabs/tasks.html", ctx)
    elif tab == "analytics":
        return templates.TemplateResponse("campaigns/tabs/analytics.html", ctx)
    else:
        return HTMLResponse(content="", status_code=404)


@router.get("/{id}/posts/{post_id}/detail", response_class=HTMLResponse)
def campaign_post_detail(
    request: Request,
    id: UUID,
    post_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)
    if campaign is None:
        return HTMLResponse(
            content="<p class='text-sm text-red-500'>Campaign not found</p>",
            status_code=404,
        )

    post_svc = PostService(db)
    post = post_svc.get_by_id(post_id)
    if post is None or post.campaign_id != campaign.id:
        return HTMLResponse(
            content="<p class='text-sm text-red-500'>Post not found</p>",
            status_code=404,
        )

    ctx = {
        "request": request,
        "campaign": campaign,
    }
    ctx.update(_build_post_detail_ctx(db, campaign=campaign, post=post))
    return templates.TemplateResponse("campaigns/tabs/post_detail.html", ctx)


@router.get("/{id}/edit", response_class=HTMLResponse)
def edit_campaign_form(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Render campaign edit form."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, record, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )

    ctx = {
        "request": request,
        "title": f"Edit {record.name}",
        "mode": "edit",
        "campaign": record,
        "statuses": [s.value for s in CampaignStatus],
    }
    return templates.TemplateResponse("campaigns/form.html", ctx)


@router.post("/{id}/edit", response_model=None)
async def edit_campaign_submit(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle campaign edit form submission."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, record, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )

    form = await request.form()
    data = CampaignUpdate(
        name=str(form.get("name", "")) or None,
        description=str(form.get("description", "")) or None,
        status=CampaignStatus(str(form.get("status", "")))
        if form.get("status")
        else None,
        start_date=str(form.get("start_date", "")) or None,
        end_date=str(form.get("end_date", "")) or None,
    )

    campaign_svc = CampaignService(db)
    try:
        campaign_svc.update(id, data)
        db.commit()
        logger.info("Campaign updated via web: %s", id)
    except ValueError:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )

    return RedirectResponse(url=f"/campaigns/{id}", status_code=302)


@router.post("/{id}/archive", response_model=None)
def archive_campaign(
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Archive a campaign."""
    campaign_svc = CampaignService(db)
    record = campaign_svc.get_by_id(id)
    if record is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, record, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )
    try:
        campaign_svc.archive(id)
        db.commit()
        logger.info("Campaign archived via web: %s", id)
    except ValueError:
        pass
    return RedirectResponse(url="/campaigns", status_code=302)


# ── Post CRUD routes ────────────────────────────────────────────────────────


def _connected_channels(db: Session) -> list[Channel]:
    """Return channels that are connected and support publishing."""
    stmt = (
        select(Channel)
        .where(Channel.status == ChannelStatus.connected)
        .where(Channel.provider.in_(PUBLISHABLE_PROVIDERS))
        .order_by(Channel.name)
    )
    return list(db.scalars(stmt).all())


@router.get("/{id}/posts/create", response_class=HTMLResponse)
def create_post_form(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Render post creation form."""
    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)
    if campaign is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, campaign, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )

    channels = _connected_channels(db)
    asset_svc = AssetService(db)
    assets = asset_svc.list_all(campaign_id=id)

    channel_options, channel_warnings = _channel_selection_and_warnings(
        channels, "", []
    )
    ctx = {
        "request": request,
        "title": "New Post",
        "mode": "create",
        "campaign": campaign,
        "channels": channels,
        "channel_options": channel_options,
        "channel_warnings": channel_warnings,
        "assets": assets,
        "statuses": [s.value for s in PostStatus if s != PostStatus.published],
        "post": None,
        "selected_asset_ids": [],
        "form_title": "",
        "form_content": "",
        "form_status": PostStatus.draft.value,
        "form_scheduled_at": "",
        "delivery_overrides": {},
        **_post_form_asset_urls(campaign.id),
    }
    return templates.TemplateResponse("campaigns/post_form.html", ctx)


@router.post("/{id}/posts/create", response_model=None)
async def create_post_submit(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Handle post creation form submission."""
    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)
    if campaign is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, campaign, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )

    form = await request.form()
    channel_ids = _parse_channel_ids(form)
    content = str(form.get("content", "") or "")
    content_overrides = _parse_content_overrides(form, channel_ids)
    selected_asset_ids: list[UUID] = []
    for asset_id in form.getlist("asset_ids") or []:
        with contextlib.suppress(ValueError, TypeError):
            selected_asset_ids.append(UUID(str(asset_id)))

    scheduled_at_str = str(form.get("scheduled_at", "")).strip()
    scheduled_at = None
    if scheduled_at_str:
        with contextlib.suppress(ValueError):
            scheduled_at = datetime.fromisoformat(scheduled_at_str)

    status_val = str(form.get("status", "draft"))
    status = PostStatus.draft
    with contextlib.suppress(ValueError):
        status = PostStatus(status_val)

    try:
        data = PostCreate(
            title=str(form.get("title", "")),
            content=content or None,
            status=status,
            campaign_id=id,
            channel_id=channel_ids[0] if channel_ids else None,
            channel_ids=channel_ids,
            scheduled_at=scheduled_at,
        )
    except (ValueError, TypeError) as exc:
        channels = _connected_channels(db)
        channel_options, channel_warnings = _channel_selection_and_warnings(
            channels, content, channel_ids, content_overrides
        )
        asset_svc = AssetService(db)
        assets = asset_svc.list_all(campaign_id=id)
        ctx = {
            "request": request,
            "title": "New Post",
            "mode": "create",
            "campaign": campaign,
            "channels": channels,
            "channel_options": channel_options,
            "channel_warnings": channel_warnings,
            "assets": assets,
            "statuses": [s.value for s in PostStatus if s != PostStatus.published],
            "post": None,
            "selected_asset_ids": selected_asset_ids,
            "form_title": str(form.get("title", "") or ""),
            "form_content": content,
            "form_status": status.value,
            "form_scheduled_at": scheduled_at_str,
            "delivery_overrides": {
                str(channel_id): value
                for channel_id, value in content_overrides.items()
            },
            "error": str(exc),
            **_post_form_asset_urls(campaign.id),
        }
        return templates.TemplateResponse("campaigns/post_form.html", ctx)

    post_svc = PostService(db)
    post = post_svc.create(data, created_by=UUID(auth["person_id"]))
    post_svc.replace_deliveries(
        post,
        channel_ids=channel_ids,
        content=data.content,
        content_overrides=content_overrides,
    )

    # Link selected assets
    asset_ids = form.getlist("asset_ids")
    if asset_ids:
        pa_svc = PostAssetService(db)
        for aid in asset_ids:
            with contextlib.suppress(ValueError, TypeError):
                pa_svc.link_asset(post.id, UUID(str(aid)))

    db.commit()
    logger.info("Post created via web: %s for campaign %s", post.id, id)
    return RedirectResponse(
        url=f"/campaigns/{id}?success=Post+created", status_code=302
    )


@router.get("/{id}/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_post_form(
    request: Request,
    id: UUID,
    post_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Render post edit form."""
    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)
    if campaign is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, campaign, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )

    post_svc = PostService(db)
    post = post_svc.get_by_id(post_id)
    if post is None or post.campaign_id != campaign.id:
        return RedirectResponse(
            url=f"/campaigns/{id}?error=Post+not+found", status_code=302
        )

    channels = _connected_channels(db)
    selected_channel_ids = [channel.id for channel in _selected_channels(db, post)]
    delivery_overrides = _delivery_override_map(db, post)
    channel_options, channel_warnings = _channel_selection_and_warnings(
        channels,
        post.content or "",
        selected_channel_ids,
        {UUID(channel_id): value for channel_id, value in delivery_overrides.items()},
    )
    asset_svc = AssetService(db)
    assets = asset_svc.list_all(campaign_id=id)
    selected_asset_ids = [a.id for a in post.assets]

    ctx = {
        "request": request,
        "title": f"Edit Post — {post.title}",
        "mode": "edit",
        "campaign": campaign,
        "post": post,
        "channels": channels,
        "selected_channels": _selected_channels(db, post),
        "channel_options": channel_options,
        "channel_warnings": channel_warnings,
        "assets": assets,
        "statuses": (
            [PostStatus.published.value]
            if post.status == PostStatus.published
            else [s.value for s in PostStatus if s != PostStatus.published]
        ),
        "selected_asset_ids": selected_asset_ids,
        "form_title": post.title or "",
        "form_content": post.content or "",
        "form_status": post.status.value if post.status else PostStatus.draft.value,
        "form_scheduled_at": (
            post.scheduled_at.strftime("%Y-%m-%dT%H:%M") if post.scheduled_at else ""
        ),
        "delivery_overrides": delivery_overrides,
        **_post_form_asset_urls(campaign.id, post.id),
    }
    return templates.TemplateResponse("campaigns/post_form.html", ctx)


@router.post("/{id}/posts/{post_id}/edit", response_model=None)
async def edit_post_submit(
    request: Request,
    id: UUID,
    post_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> Response:
    """Handle post edit form submission."""
    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)
    if campaign is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, campaign, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )

    post_svc = PostService(db)
    post = post_svc.get_by_id(post_id)
    if post is None or post.campaign_id != campaign.id:
        return RedirectResponse(
            url=f"/campaigns/{id}?error=Post+not+found", status_code=302
        )

    form = await request.form()
    channel_ids = _parse_channel_ids(form)
    content_overrides = _parse_content_overrides(form, channel_ids)

    scheduled_at_str = str(form.get("scheduled_at", "")).strip()
    scheduled_at = None
    if scheduled_at_str:
        with contextlib.suppress(ValueError):
            scheduled_at = datetime.fromisoformat(scheduled_at_str)

    status_val = str(form.get("status", ""))
    status: PostStatus | None = None
    if status_val:
        with contextlib.suppress(ValueError):
            status = PostStatus(status_val)

    data = PostUpdate(
        title=str(form.get("title", "")) or None,
        content=str(form.get("content", "")) or None,
        status=status,
        channel_id=channel_ids[0] if channel_ids else None,
        scheduled_at=scheduled_at,
    )

    if post.status == PostStatus.published:
        pub_svc = PublishingService(db)
        try:
            pub_svc.update_published_post(
                post_id,
                title=data.title,
                content=data.content,
                channel_id=data.channel_id,
                scheduled_at=data.scheduled_at,
            )
        except (ValueError, RuntimeError, NotImplementedError) as exc:
            db.rollback()
            logger.error("Failed to update published post %s: %s", post_id, exc)
            return RedirectResponse(
                url=f"/campaigns/{id}?error=Post+update+failed:+{exc}",
                status_code=302,
            )
    else:
        post_svc.update(post_id, data)
        post_svc.replace_deliveries(
            post,
            channel_ids=channel_ids,
            content=data.content if data.content is not None else post.content,
            content_overrides=content_overrides,
        )

        # Sync asset links
        pa_svc = PostAssetService(db)
        current_asset_ids = {a.id for a in post.assets}
        new_asset_ids_raw = form.getlist("asset_ids")
        new_asset_ids: set[UUID] = set()
        for aid in new_asset_ids_raw:
            with contextlib.suppress(ValueError, TypeError):
                new_asset_ids.add(UUID(str(aid)))

        for aid in new_asset_ids - current_asset_ids:
            pa_svc.link_asset(post_id, aid)
        for aid in current_asset_ids - new_asset_ids:
            pa_svc.unlink_asset(post_id, aid)

    db.commit()
    logger.info("Post updated via web: %s", post_id)
    return RedirectResponse(
        url=f"/campaigns/{id}?success=Post+updated", status_code=302
    )


@router.post("/{id}/posts/{post_id}/delete", response_model=None)
def delete_post(
    id: UUID,
    post_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Delete a post."""
    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)
    if campaign is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, campaign, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )

    post_svc = PostService(db)
    post = post_svc.get_by_id(post_id)
    if post is None or post.campaign_id != campaign.id:
        return RedirectResponse(
            url=f"/campaigns/{id}?error=Post+not+found", status_code=302
        )

    if post.status == PostStatus.published:
        pub_svc = PublishingService(db)
        try:
            pub_svc.delete_published_post(post_id)
        except (ValueError, RuntimeError, NotImplementedError) as exc:
            db.rollback()
            logger.error("Failed to delete published post %s: %s", post_id, exc)
            return RedirectResponse(
                url=f"/campaigns/{id}?error=Post+delete+failed:+{exc}",
                status_code=302,
            )
    else:
        post_svc.delete(post_id)
    db.commit()
    logger.info("Post deleted via web: %s", post_id)
    return RedirectResponse(
        url=f"/campaigns/{id}?success=Post+deleted", status_code=302
    )


@router.post("/{id}/posts/{post_id}/publish", response_model=None)
def publish_post_now(
    id: UUID,
    post_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Publish a post immediately."""
    campaign_svc = CampaignService(db)
    campaign = campaign_svc.get_by_id(id)
    if campaign is None:
        return RedirectResponse(
            url="/campaigns?error=Campaign+not+found", status_code=302
        )
    if not _can_edit_campaign(db, campaign, UUID(auth["person_id"])):
        return RedirectResponse(
            url="/campaigns?error=Permission+denied", status_code=302
        )

    post_svc = PostService(db)
    post = post_svc.get_by_id(post_id)
    if post is None or post.campaign_id != campaign.id:
        return RedirectResponse(
            url=f"/campaigns/{id}?error=Post+not+found", status_code=302
        )

    pub_svc = PublishingService(db)
    try:
        pub_svc.publish(post_id)
        db.commit()
        logger.info("Post published immediately via web: %s", post_id)
        return RedirectResponse(
            url=f"/campaigns/{id}?success=Post+published", status_code=302
        )
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        db.rollback()
        logger.error("Failed to publish post %s: %s", post_id, exc)
        return RedirectResponse(
            url=f"/campaigns/{id}?error={quote_plus(str(exc))}",
            status_code=302,
        )
