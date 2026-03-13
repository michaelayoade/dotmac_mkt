"""Channel management and OAuth connection web routes."""

from __future__ import annotations

import logging
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.services.channel_service import ChannelService
from app.services.credential_service import CredentialService
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["web-channels"])


def _get_serializer():
    """Create a URL-safe timed serializer for OAuth state tokens."""
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(settings.secret_key)


# OAuth authorize URLs per provider
_OAUTH_URLS: dict[str, str] = {
    "meta_instagram": "https://www.facebook.com/v19.0/dialog/oauth",
    "meta_facebook": "https://www.facebook.com/v19.0/dialog/oauth",
    "twitter": "https://twitter.com/i/oauth2/authorize",
    "linkedin": "https://www.linkedin.com/oauth/v2/authorization",
    "google_ads": "https://accounts.google.com/o/oauth2/v2/auth",
    "google_analytics": "https://accounts.google.com/o/oauth2/v2/auth",
}

# Scopes per provider
_OAUTH_SCOPES: dict[str, str] = {
    "meta_instagram": "instagram_basic,instagram_manage_insights,pages_show_list",
    "meta_facebook": "pages_show_list,pages_read_engagement,read_insights",
    "twitter": "tweet.read users.read offline.access",
    "linkedin": "r_liteprofile r_ads_reporting",
    "google_ads": "https://www.googleapis.com/auth/adwords",
    "google_analytics": "https://www.googleapis.com/auth/analytics.readonly",
}

# Client ID settings lookup
_CLIENT_IDS: dict[str, str] = {
    "meta_instagram": settings.meta_app_id,
    "meta_facebook": settings.meta_app_id,
    "twitter": settings.twitter_client_id,
    "linkedin": settings.linkedin_client_id,
    "google_ads": settings.google_ads_client_id,
    "google_analytics": settings.google_analytics_client_id,
}

# Client secret settings lookup
_CLIENT_SECRETS: dict[str, str] = {
    "meta_instagram": settings.meta_app_secret,
    "meta_facebook": settings.meta_app_secret,
    "twitter": settings.twitter_client_secret,
    "linkedin": settings.linkedin_client_secret,
    "google_ads": settings.google_ads_client_secret,
    "google_analytics": settings.google_analytics_client_secret,
}


@router.get("", response_class=HTMLResponse)
def list_channels(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """List all channels with connection status."""
    channel_svc = ChannelService(db)
    channels = channel_svc.list_all()

    ctx = {
        "request": request,
        "title": "Channels",
        "channels": channels,
        "providers": [p.value for p in ChannelProvider],
        "success": request.query_params.get("success", ""),
        "error": request.query_params.get("error", ""),
    }
    return templates.TemplateResponse("channels/list.html", ctx)


@router.get("/{provider}/connect", response_model=None)
def initiate_oauth(
    request: Request,
    provider: str,
) -> RedirectResponse:
    """Initiate OAuth flow for a channel provider."""
    # Validate provider
    try:
        ChannelProvider(provider)
    except ValueError:
        return RedirectResponse(
            url="/channels?error=Unknown+provider", status_code=302
        )

    oauth_url = _OAUTH_URLS.get(provider)
    client_id = _CLIENT_IDS.get(provider, "")
    scopes = _OAUTH_SCOPES.get(provider, "")

    if not oauth_url or not client_id:
        return RedirectResponse(
            url="/channels?error=Provider+not+configured", status_code=302
        )

    # Generate signed state token
    serializer = _get_serializer()
    state = serializer.dumps({"provider": provider})

    callback_url = str(request.url_for("oauth_callback", provider=provider))

    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "scope": scopes,
        "response_type": "code",
        "state": state,
    }

    redirect_url = f"{oauth_url}?{urlencode(params)}"

    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,  # 10 minutes
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/{provider}/callback", response_model=None)
async def oauth_callback(
    request: Request,
    provider: str,
    code: str = "",
    state: str = "",
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Handle OAuth callback — validate state, exchange code, store credentials."""
    # Validate state token
    cookie_state = request.cookies.get("oauth_state", "")
    if not state or state != cookie_state:
        logger.warning("OAuth state mismatch for provider %s", provider)
        return RedirectResponse(
            url="/channels?error=Invalid+OAuth+state", status_code=302
        )

    serializer = _get_serializer()
    try:
        payload = serializer.loads(state, max_age=600)
    except Exception:
        logger.warning("OAuth state token expired or invalid for %s", provider)
        return RedirectResponse(
            url="/channels?error=OAuth+state+expired", status_code=302
        )

    if payload.get("provider") != provider:
        return RedirectResponse(
            url="/channels?error=Provider+mismatch", status_code=302
        )

    if not code:
        return RedirectResponse(
            url="/channels?error=No+authorization+code", status_code=302
        )

    # Exchange code for tokens via adapter
    try:
        provider_enum = ChannelProvider(provider)
    except ValueError:
        return RedirectResponse(
            url="/channels?error=Unknown+provider", status_code=302
        )

    from app.adapters.registry import get_adapter

    try:
        adapter = get_adapter(provider_enum, access_token="", account_id="")
        token_data = await adapter.connect(code)
    except (ValueError, RuntimeError) as e:
        logger.error("OAuth token exchange failed for %s: %s", provider, e)
        return RedirectResponse(
            url="/channels?error=Token+exchange+failed", status_code=302
        )

    # Encrypt and store credentials
    channel_svc = ChannelService(db)
    cred_svc = CredentialService()

    encrypted = cred_svc.encrypt(token_data)

    # Find or create channel for this provider
    from sqlalchemy import select

    stmt = select(Channel).where(Channel.provider == provider_enum)
    channel = db.scalar(stmt)

    if channel is None:
        from app.schemas.channel import ChannelCreate

        channel_data = ChannelCreate(
            name=provider.replace("_", " ").title(),
            provider=provider_enum,
        )
        channel = channel_svc.create(channel_data)

    channel_svc.store_credentials(channel.id, encrypted)
    channel_svc.update_status(channel.id, ChannelStatus.connected)
    channel_svc.update_last_synced(channel.id)
    db.commit()

    logger.info("OAuth flow completed for provider %s, channel %s", provider, channel.id)

    # Clear the state cookie
    response = RedirectResponse(
        url="/channels?success=Channel+connected+successfully", status_code=302
    )
    response.delete_cookie("oauth_state")
    return response


@router.post("/{channel_id}/disconnect", response_model=None)
def disconnect_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Disconnect a channel — clear credentials and update status."""
    channel_svc = ChannelService(db)

    try:
        channel_svc.store_credentials(channel_id, b"")
        channel_svc.update_status(channel_id, ChannelStatus.disconnected)
        db.commit()
        logger.info("Channel disconnected via web: %s", channel_id)
    except ValueError:
        return RedirectResponse(
            url="/channels?error=Channel+not+found", status_code=302
        )

    return RedirectResponse(
        url="/channels?success=Channel+disconnected", status_code=302
    )
