import logging
from datetime import date, timedelta

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.channel import Channel, ChannelStatus
from app.services.analytics_service import AnalyticsService
from app.services.channel_service import ChannelService
from app.services.credential_service import CredentialService
from app.adapters.registry import get_adapter

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
            except (ValueError, RuntimeError, ConnectionError) as e:
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


def _sync_channel(channel, cred_svc, analytics_svc, start, end):
    """Sync metrics for a single channel."""
    if not channel.credentials_encrypted:
        logger.warning("No credentials for channel %s", channel.name)
        return

    creds = cred_svc.decrypt(channel.credentials_encrypted)
    if not creds:
        logger.warning("Failed to decrypt credentials for %s", channel.name)
        return

    # Build adapter kwargs from credentials
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

    # Note: This is sync context but adapters are async
    # In production, use asyncio.run() or celery-pool-asyncio
    import asyncio
    adapter = get_adapter(channel.provider, **adapter_kwargs)
    metrics = asyncio.run(adapter.fetch_analytics(start, end))

    for m in metrics:
        analytics_svc.upsert_metric(
            channel_id=channel.id,
            metric_date=m.metric_date,
            metric_type_str=m.metric_type,
            value=m.value,
            post_id=None,  # Channel-level metrics
        )

    logger.info("Synced %d metrics for %s", len(metrics), channel.name)
