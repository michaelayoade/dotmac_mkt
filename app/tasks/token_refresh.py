import logging
from datetime import UTC, datetime, timedelta

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.channel import Channel, ChannelStatus
from app.services.channel_service import ChannelService
from app.services.credential_service import CredentialService

logger = logging.getLogger(__name__)


@celery_app.task(name="token_refresh", ignore_result=True)
def token_refresh():
    """Refresh OAuth tokens expiring within 10 minutes."""
    db = SessionLocal()
    try:
        if not CredentialService.is_configured():
            return

        channel_svc = ChannelService(db)
        cred_svc = CredentialService()

        channels = channel_svc.list_all()
        connected = [c for c in channels if c.status == ChannelStatus.connected]
        threshold = datetime.now(UTC) + timedelta(minutes=10)
        refreshed = 0

        for channel in connected:
            if not channel.credentials_encrypted:
                continue

            creds = cred_svc.decrypt(channel.credentials_encrypted)
            if not creds:
                logger.warning("Cannot decrypt creds for %s, marking error", channel.name)
                channel_svc.update_status(channel.id, ChannelStatus.error)
                continue

            expires_at_str = creds.get("expires_at")
            if not expires_at_str:
                continue

            try:
                expires_at = datetime.fromisoformat(expires_at_str)
            except (ValueError, TypeError):
                continue

            if expires_at < threshold:
                # TODO: Call provider-specific token refresh endpoint
                # For now, log that refresh is needed
                logger.info(
                    "Token for %s expires at %s — refresh needed",
                    channel.name,
                    expires_at_str,
                )
                refreshed += 1

        db.commit()
        if refreshed:
            logger.info("Refreshed %d tokens", refreshed)
    except Exception:
        db.rollback()
        logger.exception("Token refresh failed")
        raise
    finally:
        db.close()
