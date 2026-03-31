import logging
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select

from app.adapters.base import MetricData
from app.adapters.registry import get_adapter
from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.channel import ChannelProvider, ChannelStatus
from app.models.channel_metric import MetricType
from app.models.post import Post, PostStatus
from app.models.post_delivery import PostDelivery
from app.services.analytics_service import AnalyticsService
from app.services.channel_service import ChannelService
from app.services.credential_service import CredentialService

logger = logging.getLogger(__name__)


@celery_app.task(name="analytics_sync", ignore_result=True)
def analytics_sync():
    """Pull last 7 days of metrics for all connected channels."""
    db = SessionLocal()
    try:
        channel_svc = ChannelService(db)
        analytics_svc = AnalyticsService(db)

        channels = channel_svc.list_all()
        connected = [c for c in channels if c.status == ChannelStatus.connected]

        if not connected:
            logger.info("No connected channels, skipping analytics sync")
            return

        if not CredentialService.is_configured():
            logger.warning("ENCRYPTION_KEY not set, cannot decrypt credentials")
            return

        cred_svc = CredentialService()
        end = date.today()
        start = end - timedelta(days=7)

        for channel in connected:
            try:
                _sync_channel(channel, cred_svc, analytics_svc, start, end)
                channel_svc.update_last_synced(channel.id)
            except (LookupError, KeyError) as e:
                logger.warning(
                    "Skipping channel %s due to enum/key error: %s",
                    getattr(channel, "name", channel),
                    e,
                )
            except (ValueError, RuntimeError, ConnectionError, httpx.HTTPError) as e:
                logger.error("Analytics sync failed for %s: %s", channel.name, e)
                channel_svc.update_status(channel.id, ChannelStatus.error)

        db.commit()
        logger.info("Analytics sync completed for %d channels", len(connected))
    except Exception:
        db.rollback()
        logger.exception("Analytics sync failed")
        raise
    finally:
        db.close()


def sync_post_metrics_now(post: Post, db) -> None:
    """Sync metrics for the channels attached to a single post."""
    if post.status != PostStatus.published:
        return

    channels = []
    if post.deliveries:
        channels.extend(
            delivery.channel
            for delivery in post.deliveries
            if delivery.channel is not None
            and delivery.channel.status == ChannelStatus.connected
        )
    elif post.channel is not None and post.channel.status == ChannelStatus.connected:
        channels.append(post.channel)

    if not channels or not CredentialService.is_configured():
        return

    analytics_svc = AnalyticsService(db)
    try:
        cred_svc = CredentialService()
    except (ValueError, RuntimeError):
        logger.debug("Credential service unavailable, skipping on-demand sync")
        return
    end = date.today()
    start = end - timedelta(days=7)
    seen_channel_ids = set()
    for channel in channels:
        if channel.id in seen_channel_ids:
            continue
        seen_channel_ids.add(channel.id)
        try:
            _sync_channel(channel, cred_svc, analytics_svc, start, end)
        except Exception:
            logger.exception(
                "On-demand analytics sync failed for post %s on channel %s",
                post.id,
                channel.name,
            )


def _sync_channel(channel, cred_svc, analytics_svc, start, end):
    """Sync metrics for a single channel."""
    if not channel.credentials_encrypted:
        logger.warning("No credentials for channel %s", channel.name)
        return

    creds = cred_svc.decrypt(channel.credentials_encrypted)
    if not creds:
        logger.warning("Failed to decrypt credentials for %s", channel.name)
        return

    # Note: This is sync context but adapters are async
    # In production, use asyncio.run() or celery-pool-asyncio
    import asyncio

    adapter, _ = asyncio.run(
        _build_live_adapter(channel, creds, cred_svc, analytics_svc.db)
    )
    _sync_external_post_ids(channel, adapter, analytics_svc, start)
    metrics = asyncio.run(adapter.fetch_analytics(start, end))
    post_id_map = _load_post_id_map(analytics_svc, channel.id, metrics)

    for m in metrics:
        try:
            mt = MetricType(m.metric_type)
        except ValueError:
            logger.warning(
                "Unknown metric type %s from %s, skipping", m.metric_type, channel.name
            )
            continue
        analytics_svc.upsert_metric(
            channel_id=channel.id,
            metric_date=m.metric_date,
            metric_type=mt,
            value=m.value,
            post_id=post_id_map.get(str(m.post_id)) if m.post_id else None,
        )

    logger.info("Synced %d metrics for %s", len(metrics), channel.name)


def _is_manual_access_token_only(creds: dict) -> bool:
    return bool(creds.get("manual_token")) and not bool(creds.get("refresh_token"))


def _adapter_kwargs(channel, creds: dict) -> dict[str, str]:
    adapter_kwargs = {"access_token": creds.get("access_token", "")}
    if "account_id" in creds:
        adapter_kwargs["account_id"] = creds["account_id"]
    if "organization_id" in creds:
        adapter_kwargs["organization_id"] = creds["organization_id"]
    if "customer_id" in creds:
        adapter_kwargs["customer_id"] = creds["customer_id"]
    if "developer_token" in creds:
        adapter_kwargs["developer_token"] = creds["developer_token"]
    if "property_id" in creds:
        adapter_kwargs["property_id"] = creds["property_id"]
    return adapter_kwargs


async def _build_live_adapter(channel, creds, cred_svc, db):
    adapter = get_adapter(channel.provider, **_adapter_kwargs(channel, creds))
    validate_connection = getattr(adapter, "validate_connection", None)
    if validate_connection is None:
        return adapter, creds
    if await validate_connection():
        return adapter, creds

    if _is_manual_access_token_only(creds):
        raise RuntimeError(
            f"{channel.name} token is invalid; manual access tokens are not auto-refreshed"
        )

    refreshed = await _refresh_channel_for_sync(channel, creds, cred_svc, db)
    if refreshed is None:
        raise RuntimeError(
            f"{channel.name} token is invalid and could not be refreshed"
        )
    return get_adapter(
        channel.provider, **_adapter_kwargs(channel, refreshed)
    ), refreshed


async def _refresh_channel_for_sync(channel, creds, cred_svc, db):
    refresh_token_value = creds.get("refresh_token") or creds.get("access_token")
    if not refresh_token_value:
        return None

    adapter = get_adapter(channel.provider, **_adapter_kwargs(channel, creds))
    token_data = await adapter.refresh_token(refresh_token_value)
    if not token_data:
        return None

    merged = {**creds, **token_data}
    expires_in = token_data.get("expires_in")
    if expires_in:
        merged["expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=int(expires_in))
        ).isoformat()

    channel.credentials_encrypted = cred_svc.encrypt(merged)
    db.flush()
    logger.info("Refreshed token on demand for %s during analytics sync", channel.name)
    return merged


def _sync_external_post_ids(channel, adapter, analytics_svc, start: date) -> None:
    """Attach remote external IDs to local posts before analytics metrics are mapped."""
    import asyncio

    try:
        remote_posts = asyncio.run(adapter.fetch_posts(None))
    except Exception:
        logger.exception("Failed to fetch remote posts for %s", channel.name)
        return

    _reconcile_removed_remote_posts(channel, remote_posts, analytics_svc)

    matched = 0
    for remote_post in remote_posts:
        external_id = (remote_post.external_id or "").strip()
        if not external_id:
            continue

        existing = analytics_svc.db.scalar(
            select(Post.id).where(
                Post.channel_id == channel.id,
                Post.external_post_id == external_id,
            )
        )
        if existing is None:
            existing = analytics_svc.db.scalar(
                select(PostDelivery.post_id).where(
                    PostDelivery.channel_id == channel.id,
                    PostDelivery.external_post_id == external_id,
                )
            )
        if existing is not None:
            continue

        match = _match_local_post(channel.id, remote_post, analytics_svc)
        if match is None:
            continue

        match.external_post_id = external_id
        matched += 1

    if matched:
        analytics_svc.db.flush()
        logger.info("Matched %d remote posts for %s", matched, channel.name)


def _reconcile_removed_remote_posts(channel, remote_posts, analytics_svc) -> None:
    """Remove local Facebook posts that no longer exist remotely.

    Only single-target Facebook posts are deleted here. Multi-delivery posts are left
    alone so sync does not silently remove content that may still exist on other channels.
    """
    if channel.provider != ChannelProvider.meta_facebook:
        return

    remote_ids = {
        (remote_post.external_id or "").strip()
        for remote_post in remote_posts
        if (remote_post.external_id or "").strip()
    }
    if not remote_ids:
        logger.info(
            "Remote Facebook fetch for %s returned no post IDs; skipping deletion reconciliation",
            channel.name,
        )
        return

    db = analytics_svc.db
    local_posts = list(
        db.scalars(
            select(Post).where(
                Post.channel_id == channel.id,
                Post.status == PostStatus.published,
                Post.external_post_id.is_not(None),
            )
        ).all()
    )
    removed = 0
    for post in local_posts:
        external_id = (post.external_post_id or "").strip()
        if not external_id or external_id in remote_ids:
            continue
        if post.deliveries:
            continue
        db.delete(post)
        removed += 1

    local_deliveries = list(
        db.scalars(
            select(PostDelivery).where(
                PostDelivery.channel_id == channel.id,
                PostDelivery.external_post_id.is_not(None),
            )
        ).all()
    )
    for delivery in local_deliveries:
        external_id = (delivery.external_post_id or "").strip()
        if not external_id or external_id in remote_ids:
            continue
        post = delivery.post
        if post is None:
            continue
        if len(post.deliveries) != 1:
            logger.info(
                "Facebook delivery %s missing remotely for multi-delivery post %s; leaving local record intact",
                delivery.id,
                post.id,
            )
            continue
        db.delete(post)
        removed += 1

    if removed:
        db.flush()
        logger.info(
            "Removed %d local Facebook posts missing remotely for %s",
            removed,
            channel.name,
        )


def _match_local_post(channel_id, remote_post, analytics_svc):
    normalized_content = (remote_post.content or "").strip()
    normalized_title = (remote_post.title or "").strip()

    stmt = select(Post).where(Post.channel_id == channel_id)
    if remote_post.published_at is not None:
        start_dt = remote_post.published_at - timedelta(days=1)
        end_dt = remote_post.published_at + timedelta(days=1)
        stmt = stmt.where(Post.published_at.is_not(None)).where(
            Post.published_at >= start_dt,
            Post.published_at <= end_dt,
        )

    candidates = list(analytics_svc.db.scalars(stmt).all())
    if not candidates:
        return None

    def _matches(post: Post) -> bool:
        if normalized_content and (post.content or "").strip() == normalized_content:
            return True
        return bool(normalized_title and post.title.strip() == normalized_title)

    matches = [post for post in candidates if _matches(post)]
    if len(matches) == 1:
        return matches[0]
    return None


def _load_post_id_map(
    analytics_svc: AnalyticsService, channel_id, metrics: list[MetricData]
) -> dict[str, object]:
    external_ids = sorted({str(m.post_id) for m in metrics if m.post_id})
    if not external_ids:
        return {}

    stmt = select(Post.external_post_id, Post.id).where(
        Post.channel_id == channel_id,
        Post.external_post_id.in_(external_ids),
    )
    rows = analytics_svc.db.execute(stmt).all()
    post_id_map = {
        str(row.external_post_id): row.id
        for row in rows
        if row.external_post_id is not None
    }
    delivery_rows = analytics_svc.db.execute(
        select(PostDelivery.external_post_id, PostDelivery.post_id).where(
            PostDelivery.channel_id == channel_id,
            PostDelivery.external_post_id.in_(external_ids),
        )
    ).all()
    for row in delivery_rows:
        if row.external_post_id is not None:
            post_id_map[str(row.external_post_id)] = row.post_id
    return post_id_map
