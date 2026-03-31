import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.adapters.registry import get_adapter
from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.channel import ChannelStatus
from app.services.channel_integration_settings import get_meta_oauth_config
from app.services.channel_service import ChannelService
from app.services.credential_service import CredentialService

logger = logging.getLogger(__name__)

# Map providers to the adapter kwargs key for account/org/customer/property ID
_PROVIDER_KEY_MAP: dict[str, str] = {
    "meta_instagram": "account_id",
    "meta_facebook": "account_id",
    "meta_ads": "account_id",
    "twitter": "account_id",
    "linkedin": "organization_id",
    "google_ads": "customer_id",
    "google_analytics": "property_id",
}


def _is_manual_access_token_only(creds: dict) -> bool:
    return bool(creds.get("manual_token")) and not bool(creds.get("refresh_token"))


async def _refresh_channel_token(channel, creds, cred_svc, channel_svc, db) -> bool:
    """Attempt to refresh a single channel's token. Returns True on success."""
    if _is_manual_access_token_only(creds):
        logger.info(
            "Skipping token refresh for %s because it uses a manual access token only",
            channel.name,
        )
        return False

    refresh_token_value = creds.get("refresh_token") or creds.get("access_token")
    if not refresh_token_value:
        logger.warning("No refresh token for %s, skipping", channel.name)
        return False

    provider = channel.provider.value
    extra_key = _PROVIDER_KEY_MAP.get(provider, "account_id")
    adapter_kwargs = {
        "access_token": creds.get("access_token", ""),
        extra_key: channel.external_account_id or "",
    }
    if channel.provider.value in {"meta_instagram", "meta_facebook", "meta_ads"}:
        meta_config = get_meta_oauth_config(db)
        adapter_kwargs["client_id"] = meta_config.app_id
        adapter_kwargs["client_secret"] = meta_config.app_secret
        adapter_kwargs["graph_version"] = meta_config.graph_version
        adapter_kwargs["timeout_seconds"] = meta_config.api_timeout_seconds

    try:
        adapter = get_adapter(channel.provider, **adapter_kwargs)
        new_token_data = await adapter.refresh_token(refresh_token_value)
    except (ValueError, RuntimeError) as e:
        logger.error("Adapter error refreshing %s: %s", channel.name, e)
        return False

    if not new_token_data:
        logger.warning("Token refresh returned no data for %s", channel.name)
        channel_svc.update_status(channel.id, ChannelStatus.error)
        return False

    # Merge new token data into existing creds (preserves refresh_token if not returned)
    merged = {**creds, **new_token_data}

    # Set expires_at if expires_in is present
    expires_in = new_token_data.get("expires_in")
    if expires_in:
        expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
        merged["expires_at"] = expires_at.isoformat()

    encrypted = cred_svc.encrypt(merged)
    channel_svc.store_credentials(channel.id, encrypted)
    channel_svc.update_last_synced(channel.id)
    logger.info("Token refreshed for %s", channel.name)
    return True


def _process_channel_refresh(channel, cred_svc, channel_svc, db, threshold) -> None:
    """Evaluate and refresh a single channel's token if near expiry."""
    if not channel.credentials_encrypted:
        return

    creds = cred_svc.decrypt(channel.credentials_encrypted)
    if not creds:
        logger.warning("Cannot decrypt creds for %s, marking error", channel.name)
        channel_svc.update_status(channel.id, ChannelStatus.error)
        return

    expires_at_str = creds.get("expires_at")
    if not expires_at_str:
        return

    try:
        expires_at = datetime.fromisoformat(expires_at_str)
    except (ValueError, TypeError):
        return

    if expires_at < threshold:
        asyncio.run(_refresh_channel_token(channel, creds, cred_svc, channel_svc, db))


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
            try:
                _process_channel_refresh(channel, cred_svc, channel_svc, db, threshold)
                refreshed += 1
            except (LookupError, KeyError) as e:
                logger.warning(
                    "Skipping channel %s due to enum/key error: %s",
                    getattr(channel, "name", channel),
                    e,
                )
            except (ValueError, RuntimeError, ConnectionError) as e:
                logger.error("Token refresh error for %s: %s", channel.name, e)

        db.commit()
        if refreshed:
            logger.info("Refreshed %d tokens", refreshed)
    except Exception:
        db.rollback()
        logger.exception("Token refresh failed")
        raise
    finally:
        db.close()
