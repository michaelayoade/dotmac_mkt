"""Periodic sync of ad campaign hierarchy and metrics from ad platforms."""

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.adapters.registry import get_adapter
from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.ad_campaign import AdPlatform
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.services.ad_sync_service import AdSyncService
from app.services.credential_service import CredentialService

logger = logging.getLogger(__name__)

AD_CHANNEL_MAP: dict[ChannelProvider, AdPlatform] = {
    ChannelProvider.meta_ads: AdPlatform.meta,
    ChannelProvider.google_ads: AdPlatform.google,
    ChannelProvider.linkedin_ads: AdPlatform.linkedin,
}

DEFAULT_LOOKBACK_DAYS = 7


def _build_adapter_kwargs(creds: dict) -> dict[str, str]:
    kwargs: dict[str, str] = {"access_token": creds.get("access_token", "")}
    for key in (
        "account_id",
        "organization_id",
        "customer_id",
        "property_id",
        "developer_token",
    ):
        if key in creds:
            kwargs[key] = creds[key]
    return kwargs


def _sync_channel(
    db,
    channel: Channel,
    platform: AdPlatform,
    start_date: date,
    end_date: date,
) -> int:
    """Sync a single ad channel. Returns count of metrics upserted."""
    cred_svc = CredentialService()
    if not channel.credentials_encrypted:
        logger.warning("Channel %s has no credentials, skipping ad sync", channel.name)
        return 0

    creds = cred_svc.decrypt(channel.credentials_encrypted)
    if not creds:
        logger.warning("Failed to decrypt credentials for %s", channel.name)
        return 0

    adapter_kwargs = _build_adapter_kwargs(creds)
    adapter = get_adapter(channel.provider, **adapter_kwargs)

    if not hasattr(adapter, "fetch_ads_history"):
        logger.info("Adapter for %s has no fetch_ads_history, skipping", channel.name)
        return 0

    rows = asyncio.run(adapter.fetch_ads_history(start_date, end_date))
    if not rows:
        logger.info("No ad history returned for %s", channel.name)
        return 0

    sync_svc = AdSyncService(db)
    count = sync_svc.sync_platform_rows(channel.id, platform, rows)
    logger.info(
        "Ad sync for %s (%s): %d metrics upserted from %d rows",
        channel.name,
        platform.value,
        count,
        len(rows),
    )
    return count


@celery_app.task(name="ad_sync", ignore_result=True)
def ad_sync() -> None:
    """Sync ad campaigns, ad groups, ads, and daily metrics for all ad channels."""
    db = SessionLocal()
    try:
        if not CredentialService.is_configured():
            logger.warning("ENCRYPTION_KEY not set, cannot decrypt credentials")
            return

        stmt = (
            select(Channel)
            .where(Channel.status == ChannelStatus.connected)
            .where(Channel.provider.in_(list(AD_CHANNEL_MAP.keys())))
        )
        channels = list(db.scalars(stmt).all())

        if not channels:
            logger.info("No connected ad channels, skipping ad sync")
            return

        end_date = date.today()
        start_date = end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        total = 0

        for channel in channels:
            platform = AD_CHANNEL_MAP[channel.provider]
            try:
                total += _sync_channel(db, channel, platform, start_date, end_date)
            except (ValueError, RuntimeError, NotImplementedError) as exc:
                logger.error("Ad sync failed for %s: %s", channel.name, exc)
                continue

        db.commit()
        logger.info("Ad sync complete: %d total metrics upserted", total)
    except Exception:
        db.rollback()
        logger.exception("Ad sync task failed")
        raise
    finally:
        db.close()
