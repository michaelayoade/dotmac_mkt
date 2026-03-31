"""Channel management and OAuth connection web routes."""

from __future__ import annotations

import hashlib
import logging
import secrets
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from itsdangerous import BadData, BadSignature, SignatureExpired
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import get_adapter
from app.api.deps import get_db
from app.config import settings
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.schemas.channel import ChannelCreate
from app.services.channel_integration_settings import get_meta_oauth_config
from app.services.channel_service import ChannelService
from app.services.credential_service import CredentialService
from app.services.marketing_runtime import get_marketing_value
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["web-channels"])


def _canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = (settings.canonical_scheme or parts.scheme or "https").strip()
    host = (settings.canonical_host or parts.netloc).strip()
    if not host:
        host = parts.netloc
    return urlunsplit((scheme, host, parts.path, parts.query, parts.fragment))


def _external_redirect_response(url: str) -> HTMLResponse:
    escaped = (
        url.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return HTMLResponse(
        content=(
            "<!doctype html><html><head>"
            f'<meta http-equiv="refresh" content="0;url={escaped}">'
            '<meta name="referrer" content="no-referrer">'
            "<title>Redirecting...</title>"
            "</head><body>"
            f"<script>window.location.replace({url!r});</script>"
            f'<p>Redirecting to OAuth provider. If nothing happens, <a href="{escaped}">continue here</a>.</p>'
            "</body></html>"
        ),
        status_code=200,
    )


_PROVIDER_KEY_MAP: dict[str, str] = {
    "meta_instagram": "account_id",
    "meta_facebook": "account_id",
    "meta_ads": "account_id",
    "twitter": "account_id",
    "linkedin": "organization_id",
    "google_ads": "customer_id",
    "google_analytics": "property_id",
}

_PROVIDER_LABELS: dict[str, str] = {
    "meta_instagram": "Instagram account ID",
    "meta_facebook": "Facebook page ID",
    "meta_ads": "Meta ad account ID",
    "twitter": "X account ID",
    "linkedin": "LinkedIn organization ID",
    "google_ads": "Google Ads customer ID",
    "google_analytics": "GA4 property ID",
}

_PROVIDER_PLACEHOLDERS: dict[str, str] = {
    "meta_instagram": "17841400000000000",
    "meta_facebook": "123456789012345",
    "meta_ads": "123456789012345",
    "twitter": "2244994945",
    "linkedin": "12345678",
    "google_ads": "1234567890",
    "google_analytics": "123456789",
}

_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    provider.value: label.replace(" ID", "")
    for provider, label in (
        (ChannelProvider.meta_instagram, _PROVIDER_LABELS["meta_instagram"]),
        (ChannelProvider.meta_facebook, _PROVIDER_LABELS["meta_facebook"]),
        (ChannelProvider.meta_ads, _PROVIDER_LABELS["meta_ads"]),
        (ChannelProvider.twitter, _PROVIDER_LABELS["twitter"]),
        (ChannelProvider.linkedin, _PROVIDER_LABELS["linkedin"]),
        (ChannelProvider.google_ads, _PROVIDER_LABELS["google_ads"]),
        (ChannelProvider.google_analytics, _PROVIDER_LABELS["google_analytics"]),
    )
}

_META_PROVIDER_VALUES = {
    ChannelProvider.meta_facebook.value,
    ChannelProvider.meta_instagram.value,
    ChannelProvider.meta_ads.value,
}
_META_COMBINED_SCOPE = (
    "pages_show_list,pages_read_engagement,instagram_basic,"
    "instagram_manage_insights,ads_read,business_management"
)


def _get_serializer():
    """Create a URL-safe timed serializer for OAuth state tokens."""
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(settings.secret_key)


def _extract_external_account_id(
    provider: str,
    token_data: dict,
    requested_external_account_id: str | None,
    existing_external_account_id: str | None,
) -> str:
    provider_key = _PROVIDER_KEY_MAP.get(provider, "account_id")
    candidates = (
        token_data.get(provider_key),
        token_data.get("external_account_id"),
        requested_external_account_id,
        existing_external_account_id,
    )
    for candidate in candidates:
        if isinstance(candidate, str):
            value = candidate.strip()
            if value:
                return value
    return ""


def _merge_token_data_with_account_id(
    provider: str, token_data: dict, external_account_id: str
) -> dict:
    merged = dict(token_data)
    merged["external_account_id"] = external_account_id
    merged[_PROVIDER_KEY_MAP.get(provider, "account_id")] = external_account_id
    return merged


def _channel_context(
    request: Request,
    auth: dict,
    *,
    title: str,
    page_title: str,
    **extra: object,
) -> dict[str, object]:
    ctx: dict[str, object] = {
        "request": request,
        "title": title,
        "page_title": page_title,
        "current_user": auth.get("person"),
        "provider_labels": _PROVIDER_LABELS,
        "provider_placeholders": _PROVIDER_PLACEHOLDERS,
        "provider_display_names": _PROVIDER_DISPLAY_NAMES,
        "success": request.query_params.get("success", ""),
        "error": request.query_params.get("error", ""),
        "success_message": request.query_params.get("success", ""),
        "error_message": request.query_params.get("error", ""),
    }
    ctx.update(extra)
    return ctx


def _ensure_default_channels(channel_svc: ChannelService, db: Session) -> list[Channel]:
    existing = list(db.scalars(select(Channel).order_by(Channel.name)).all())
    existing_by_provider = {channel.provider for channel in existing}
    created = False

    for provider in ChannelProvider:
        if provider in existing_by_provider:
            continue
        channel_svc.create(
            ChannelCreate(
                name=_PROVIDER_DISPLAY_NAMES.get(
                    provider.value, provider.value.replace("_", " ").title()
                ),
                provider=provider,
            )
        )
        created = True

    if created:
        db.commit()
        existing = list(db.scalars(select(Channel).order_by(Channel.name)).all())

    return existing


def _get_or_create_channel(
    db: Session,
    channel_svc: ChannelService,
    provider: ChannelProvider,
    external_account_id: str,
    name: str | None = None,
) -> Channel:
    if external_account_id:
        channel = db.scalar(
            select(Channel).where(
                Channel.provider == provider,
                Channel.external_account_id == external_account_id,
            )
        )
        if channel is not None:
            if name:
                channel.name = name
                db.flush()
            return channel

    channel = db.scalar(
        select(Channel).where(
            Channel.provider == provider,
            Channel.external_account_id.is_(None),
        )
    )
    if channel is not None:
        channel.external_account_id = external_account_id or channel.external_account_id
        if name:
            channel.name = name
        db.flush()
        return channel

    return channel_svc.create(
        ChannelCreate(
            name=name
            or _PROVIDER_DISPLAY_NAMES.get(
                provider.value, provider.value.replace("_", " ").title()
            ),
            provider=provider,
        )
    )


def _store_channel_connection(
    db: Session,
    channel_svc: ChannelService,
    cred_svc: CredentialService,
    *,
    provider: ChannelProvider,
    token_data: dict,
    external_account_id: str,
    name: str | None = None,
) -> Channel:
    channel = _get_or_create_channel(
        db, channel_svc, provider, external_account_id, name=name
    )
    enriched_token_data = _merge_token_data_with_account_id(
        provider.value, token_data, external_account_id
    )
    encrypted = cred_svc.encrypt(enriched_token_data)
    channel_svc.store_credentials(channel.id, encrypted)
    channel_svc.update_external_account_id(channel.id, external_account_id)
    channel_svc.update_status(channel.id, ChannelStatus.connected)
    channel_svc.update_last_synced(channel.id)
    return channel


def _resolve_manual_provider(
    provider: str, external_account_id: str, db: Session
) -> ChannelProvider:
    if provider != "meta":
        return ChannelProvider(provider)

    account_id = external_account_id.strip()
    if account_id:
        existing = db.scalar(
            select(Channel.provider).where(
                Channel.provider.in_(
                    [ChannelProvider.meta_facebook, ChannelProvider.meta_instagram]
                ),
                Channel.external_account_id == account_id,
            )
        )
        if existing is not None:
            return existing

    # Instagram business account IDs commonly begin with 1784 and are longer
    # than Facebook page IDs, which makes this a practical fallback when the
    # user submits the combined `meta` provider.
    if account_id.startswith("1784") or len(account_id) >= 16:
        return ChannelProvider.meta_instagram
    return ChannelProvider.meta_facebook


async def _discover_meta_assets(
    access_token: str,
    *,
    graph_version: str,
    timeout_seconds: int,
) -> list[dict[str, str]]:
    graph_api = f"https://graph.facebook.com/{graph_version}"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(
                f"{graph_api}/me/accounts",
                params={
                    "fields": "id,name,access_token,instagram_business_account{id,username,name}",
                    "access_token": access_token,
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.error("Meta asset discovery failed: %s", exc)
        return []

    ad_accounts_data: dict[str, object] = {"data": []}
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            ad_accounts_response = await client.get(
                f"{graph_api}/me/adaccounts",
                params={
                    "fields": "id,account_id,name,account_status,currency",
                    "access_token": access_token,
                },
            )
            ad_accounts_response.raise_for_status()
            ad_accounts_data = ad_accounts_response.json()
    except httpx.HTTPError as exc:
        logger.warning("Meta ad account discovery skipped: %s", exc)

    assets: list[dict[str, str]] = []
    for page in data.get("data", []):
        page_id = str(page.get("id", "")).strip()
        page_name = str(page.get("name", "")).strip() or "Facebook Page"
        page_token = str(page.get("access_token", "")).strip() or access_token
        if page_id:
            assets.append(
                {
                    "provider": ChannelProvider.meta_facebook.value,
                    "external_account_id": page_id,
                    "name": page_name,
                    "access_token": page_token,
                }
            )
        instagram = page.get("instagram_business_account") or {}
        instagram_id = str(instagram.get("id", "")).strip()
        instagram_name = (
            str(instagram.get("username", "")).strip()
            or str(instagram.get("name", "")).strip()
            or "Instagram Account"
        )
        if instagram_id:
            assets.append(
                {
                    "provider": ChannelProvider.meta_instagram.value,
                    "external_account_id": instagram_id,
                    "name": instagram_name,
                    "access_token": page_token,
                }
            )

    for account in ad_accounts_data.get("data", []):
        raw_account_id = str(
            account.get("account_id") or account.get("id") or ""
        ).strip()
        if not raw_account_id:
            continue
        assets.append(
            {
                "provider": ChannelProvider.meta_ads.value,
                "external_account_id": raw_account_id.removeprefix("act_"),
                "name": str(account.get("name", "")).strip() or "Meta Ad Account",
                "access_token": access_token,
            }
        )
    return assets


# OAuth authorize URLs per provider
_OAUTH_URLS: dict[str, str] = {
    "meta_instagram": "https://www.facebook.com/v19.0/dialog/oauth",
    "meta_facebook": "https://www.facebook.com/v19.0/dialog/oauth",
    "meta_ads": "https://www.facebook.com/v19.0/dialog/oauth",
    "twitter": "https://twitter.com/i/oauth2/authorize",
    "linkedin": "https://www.linkedin.com/oauth/v2/authorization",
    "google_ads": "https://accounts.google.com/o/oauth2/v2/auth",
    "google_analytics": "https://accounts.google.com/o/oauth2/v2/auth",
}

# Scopes per provider
_OAUTH_SCOPES: dict[str, str] = {
    "meta_instagram": "pages_show_list,pages_read_engagement,instagram_basic,instagram_manage_insights",
    "meta_facebook": "pages_show_list,pages_read_engagement",
    "meta_ads": "ads_read,business_management",
    "twitter": "tweet.read users.read offline.access",
    "linkedin": "r_liteprofile r_ads_reporting",
    "google_ads": "https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.metadata.readonly",
    "google_analytics": "https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.metadata.readonly",
}


def _client_id_for_provider(provider: str, db: Session | None = None) -> str:
    if provider in _META_PROVIDER_VALUES:
        if db is not None:
            return get_meta_oauth_config(db).app_id
        return get_marketing_value("meta_app_id")

    provider_keys = {
        "twitter": "twitter_client_id",
        "linkedin": "linkedin_client_id",
        "google_ads": "google_ads_client_id",
        "google_analytics": "google_analytics_client_id",
    }
    key = provider_keys.get(provider)
    if not key:
        return ""
    return get_marketing_value(key, db)


@router.get("", response_class=HTMLResponse)
def list_channels(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List all channels with connection status and recent metrics."""
    from datetime import date, timedelta

    from app.services.analytics_service import AnalyticsService

    channel_svc = ChannelService(db)
    channels = _ensure_default_channels(channel_svc, db)

    # Per-channel metrics for the last 30 days
    analytics_svc = AnalyticsService(db)
    today = date.today()
    d_start = today - timedelta(days=30)
    channel_metrics: dict[str, dict[str, int]] = {}
    for ch in channels:
        raw = analytics_svc.get_channel_metrics(
            ch.id, start_date=d_start, end_date=today
        )
        totals: dict[str, float] = {}
        for m in raw:
            totals[m.metric_type.value] = totals.get(m.metric_type.value, 0) + float(
                m.value
            )
        channel_metrics[str(ch.id)] = {
            "impressions": int(totals.get("impressions", 0)),
            "reach": int(totals.get("reach", 0)),
            "clicks": int(totals.get("clicks", 0)),
            "engagement": int(totals.get("engagement", 0)),
        }

    ctx = _channel_context(
        request,
        auth,
        title="Channels",
        page_title="Channels",
        channels=channels,
        channel_metrics=channel_metrics,
        providers=[p.value for p in ChannelProvider],
    )
    return templates.TemplateResponse("channels/list.html", ctx)


@router.get("/create", response_class=HTMLResponse)
def create_channel_form(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    channel_svc = ChannelService(db)
    channels = _ensure_default_channels(channel_svc, db)
    provider_options = [
        {
            "value": "meta",
            "label": "Meta (Facebook + Instagram)",
        },
    ] + [
        {
            "value": provider.value,
            "label": _PROVIDER_DISPLAY_NAMES.get(
                provider.value, provider.value.replace("_", " ").title()
            ),
        }
        for provider in ChannelProvider
    ]
    ctx = _channel_context(
        request,
        auth,
        title="Connect Channel",
        page_title="Connect Channel",
        provider_options=provider_options,
        channels=channels,
        form_data={},
    )
    return templates.TemplateResponse("channels/create.html", ctx)


@router.post("/create", response_model=None)
async def create_channel_submit(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    form = await request.form()
    provider = str(form.get("provider", "")).strip()
    external_account_id = str(form.get("external_account_id", "")).strip()

    if provider == "meta":
        return _build_meta_oauth_redirect(request, db)

    try:
        provider_enum = ChannelProvider(provider)
    except ValueError:
        ctx = _channel_context(
            request,
            auth,
            title="Connect Channel",
            page_title="Connect Channel",
            provider_options=[
                {
                    "value": "meta",
                    "label": "Meta (Facebook + Instagram)",
                },
            ]
            + [
                {
                    "value": item.value,
                    "label": _PROVIDER_DISPLAY_NAMES.get(
                        item.value, item.value.replace("_", " ").title()
                    ),
                }
                for item in ChannelProvider
            ],
            channels=[],
            error="Unknown provider",
            error_message="Unknown provider",
            form_data={
                "provider": provider,
                "external_account_id": external_account_id,
            },
        )
        return templates.TemplateResponse("channels/create.html", ctx, status_code=400)

    redirect_url = _canonicalize_url(
        str(request.url_for("initiate_oauth", provider=provider_enum.value))
    )
    if external_account_id:
        redirect_url = (
            f"{redirect_url}?{urlencode({'external_account_id': external_account_id})}"
        )
    return RedirectResponse(url=redirect_url, status_code=302)


def _build_meta_oauth_redirect(request: Request, db: Session) -> RedirectResponse:
    meta_config = get_meta_oauth_config(db)
    if not meta_config.app_id or not meta_config.app_secret:
        return RedirectResponse(
            url="/settings?error=Meta+App+credentials+are+required",
            status_code=302,
        )

    serializer = _get_serializer()
    callback_url = _canonicalize_url(str(request.url_for("meta_callback")))
    state_payload = {"provider": "meta"}
    state = serializer.dumps(state_payload)
    params = {
        "client_id": meta_config.app_id,
        "redirect_uri": callback_url,
        "scope": _META_COMBINED_SCOPE,
        "response_type": "code",
        "state": state,
    }
    redirect_url = f"{_OAUTH_URLS['meta_facebook']}?{urlencode(params)}"
    response = _external_redirect_response(redirect_url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/meta/connect", response_model=None, name="meta_connect")
def initiate_meta_oauth(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    return _build_meta_oauth_redirect(request, db)


@router.get("/meta/callback", response_model=None, name="meta_callback")
async def meta_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    cookie_state = request.cookies.get("oauth_state", "")
    if not state or state != cookie_state:
        return RedirectResponse(
            url="/channels?error=Invalid+OAuth+state", status_code=302
        )

    serializer = _get_serializer()
    try:
        payload = serializer.loads(state, max_age=600)
    except (BadSignature, SignatureExpired, BadData):
        return RedirectResponse(
            url="/channels?error=OAuth+state+expired", status_code=302
        )

    if payload.get("provider") != "meta":
        return RedirectResponse(
            url="/channels?error=Provider+mismatch", status_code=302
        )
    if not code:
        return RedirectResponse(
            url="/channels?error=No+authorization+code", status_code=302
        )

    meta_config = get_meta_oauth_config(db)
    if not meta_config.app_id or not meta_config.app_secret:
        return RedirectResponse(
            url="/settings?error=Meta+App+credentials+are+required",
            status_code=302,
        )

    callback_url = _canonicalize_url(str(request.url_for("meta_callback")))
    try:
        adapter = get_adapter(
            ChannelProvider.meta_facebook,
            access_token="",
            account_id="",
            client_id=meta_config.app_id,
            client_secret=meta_config.app_secret,
            graph_version=meta_config.graph_version,
            timeout_seconds=meta_config.api_timeout_seconds,
        )
        token_data = await adapter.connect(code, redirect_uri=callback_url)
    except (ValueError, RuntimeError) as e:
        logger.error("Meta OAuth token exchange failed: %s", e)
        return RedirectResponse(
            url="/channels?error=Token+exchange+failed", status_code=302
        )

    channel_svc = ChannelService(db)
    cred_svc = CredentialService()
    assets = await _discover_meta_assets(
        token_data.get("access_token", ""),
        graph_version=meta_config.graph_version,
        timeout_seconds=meta_config.api_timeout_seconds,
    )
    if not assets:
        return RedirectResponse(
            url="/channels?error=No+Meta+pages+or+Instagram+accounts+found",
            status_code=302,
        )

    connected_any = False
    for asset in assets:
        provider_value = asset.get("provider", "")
        external_account_id = asset.get("external_account_id", "")
        if not provider_value or not external_account_id:
            continue
        provider_enum = ChannelProvider(provider_value)
        asset_token_data = {
            **token_data,
            "access_token": asset.get(
                "access_token", token_data.get("access_token", "")
            ),
        }
        _store_channel_connection(
            db,
            channel_svc,
            cred_svc,
            provider=provider_enum,
            token_data=asset_token_data,
            external_account_id=external_account_id,
            name=asset.get("name", "") or None,
        )
        connected_any = True

    if not connected_any:
        return RedirectResponse(
            url="/channels?error=No+supported+Meta+assets+found",
            status_code=302,
        )

    db.commit()
    response = RedirectResponse(
        url="/channels?success=Meta+connected+successfully", status_code=302
    )
    response.delete_cookie("oauth_state")
    return response


@router.get("/meta/webhook", response_class=PlainTextResponse, name="meta_webhook")
def meta_webhook_verify(
    request: Request,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    meta_config = get_meta_oauth_config(db)
    mode = request.query_params.get("hub.mode", "")
    challenge = request.query_params.get("hub.challenge", "")
    verify_token = request.query_params.get("hub.verify_token", "")

    if (
        mode == "subscribe"
        and challenge
        and meta_config.webhook_verify_token
        and verify_token == meta_config.webhook_verify_token
    ):
        return PlainTextResponse(content=challenge, status_code=200)
    return PlainTextResponse(content="Forbidden", status_code=403)


@router.get("/{provider}/connect", response_model=None)
def initiate_oauth(
    request: Request,
    provider: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Initiate OAuth flow for a channel provider."""
    # Validate provider
    try:
        ChannelProvider(provider)
    except ValueError:
        return RedirectResponse(url="/channels?error=Unknown+provider", status_code=302)

    if provider in _META_PROVIDER_VALUES:
        return _build_meta_oauth_redirect(request, db)

    oauth_url = _OAUTH_URLS.get(provider)
    client_id = _client_id_for_provider(provider, db)
    scopes = _OAUTH_SCOPES.get(provider, "")

    if not oauth_url or not client_id:
        return RedirectResponse(
            url="/channels?error=Provider+not+configured", status_code=302
        )

    # Generate signed state token (includes PKCE verifier for Twitter)
    serializer = _get_serializer()
    callback_url = _canonicalize_url(
        str(request.url_for("oauth_callback", provider=provider))
    )
    requested_external_account_id = request.query_params.get(
        "external_account_id", ""
    ).strip()

    state_payload: dict[str, str] = {"provider": provider}
    if requested_external_account_id:
        state_payload["external_account_id"] = requested_external_account_id

    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "scope": scopes,
        "response_type": "code",
        "state": "",  # placeholder, set below
    }

    if provider in {"google_ads", "google_analytics"}:
        params["access_type"] = "offline"
        params["prompt"] = "consent"
        params["include_granted_scopes"] = "true"

    # Twitter requires PKCE (RFC 7636)
    if provider == "twitter":
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state_payload["code_verifier"] = code_verifier
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"

    state = serializer.dumps(state_payload)
    params["state"] = state

    redirect_url = f"{oauth_url}?{urlencode(params)}"

    response = _external_redirect_response(redirect_url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,  # 10 minutes
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/{provider}/connect", response_model=None)
async def initiate_oauth_post(
    request: Request,
    provider: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    form = await request.form()
    external_account_id = str(form.get("external_account_id", "")).strip()

    redirect_url = _canonicalize_url(
        str(request.url_for("initiate_oauth", provider=provider))
    )
    if external_account_id:
        redirect_url = (
            f"{redirect_url}?{urlencode({'external_account_id': external_account_id})}"
        )
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/{provider}/callback", response_model=None)
async def oauth_callback(
    request: Request,
    provider: str,
    code: str = "",
    state: str = "",
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
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
    except (BadSignature, SignatureExpired, BadData):
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
        return RedirectResponse(url="/channels?error=Unknown+provider", status_code=302)

    # Build provider-specific kwargs for adapter instantiation
    _adapter_kwargs: dict[str, str] = {"access_token": ""}
    _provider_key_map: dict[str, str] = {
        "meta_instagram": "account_id",
        "meta_facebook": "account_id",
        "meta_ads": "account_id",
        "twitter": "account_id",
        "linkedin": "organization_id",
        "google_ads": "customer_id",
        "google_analytics": "property_id",
    }
    extra_key = _provider_key_map.get(provider, "account_id")
    _adapter_kwargs[extra_key] = ""

    callback_url = _canonicalize_url(
        str(request.url_for("oauth_callback", provider=provider))
    )
    code_verifier = payload.get("code_verifier")

    try:
        adapter = get_adapter(provider_enum, **_adapter_kwargs)
        token_data = await adapter.connect(
            code, redirect_uri=callback_url, code_verifier=code_verifier
        )
    except (ValueError, RuntimeError) as e:
        logger.error("OAuth token exchange failed for %s: %s", provider, e)
        return RedirectResponse(
            url="/channels?error=Token+exchange+failed", status_code=302
        )

    # Encrypt and store credentials
    channel_svc = ChannelService(db)
    cred_svc = CredentialService()
    requested_external_account_id = payload.get("external_account_id", "").strip()

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

    external_account_id = _extract_external_account_id(
        provider,
        token_data,
        requested_external_account_id,
        channel.external_account_id,
    )
    if not external_account_id:
        label = _PROVIDER_LABELS.get(provider, "external account ID")
        return RedirectResponse(
            url=f"/channels?error=Missing+{label.replace(' ', '+')}",
            status_code=302,
        )

    token_data = _merge_token_data_with_account_id(
        provider, token_data, external_account_id
    )
    expires_in = token_data.get("expires_in")
    if expires_in and not token_data.get("expires_at"):
        token_data["expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=int(expires_in))
        ).isoformat()
    encrypted = cred_svc.encrypt(token_data)

    channel_svc.store_credentials(channel.id, encrypted)
    channel_svc.update_external_account_id(channel.id, external_account_id)
    channel_svc.update_status(channel.id, ChannelStatus.connected)
    channel_svc.update_last_synced(channel.id)
    db.commit()

    logger.info(
        "OAuth flow completed for provider %s, channel %s", provider, channel.id
    )

    # Clear the state cookie
    response = RedirectResponse(
        url="/channels?success=Channel+connected+successfully", status_code=302
    )
    response.delete_cookie("oauth_state")
    return response


@router.post("/{provider}/manual-connect", response_model=None)
async def manual_connect_channel(
    request: Request,
    provider: str,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    try:
        form = await request.form()
        access_token = str(form.get("access_token", "")).strip()
        refresh_token = str(form.get("refresh_token", "")).strip()
        external_account_id = str(form.get("external_account_id", "")).strip()
        provider_enum = _resolve_manual_provider(provider, external_account_id, db)
    except ValueError:
        return RedirectResponse(url="/channels?error=Unknown+provider", status_code=302)

    if not access_token:
        return RedirectResponse(
            url="/channels?error=Access+token+is+required", status_code=302
        )
    if not external_account_id:
        return RedirectResponse(
            url="/channels?error=External+account+ID+is+required", status_code=302
        )

    token_data = {"access_token": access_token, "manual_token": True}
    if refresh_token:
        token_data["refresh_token"] = refresh_token

    adapter_kwargs: dict[str, str] = {"access_token": access_token}
    provider_key = _PROVIDER_KEY_MAP.get(provider_enum.value, "account_id")
    adapter_kwargs[provider_key] = external_account_id
    try:
        adapter = get_adapter(provider_enum, **adapter_kwargs)
        if not await adapter.validate_connection():
            return RedirectResponse(
                url="/channels?error=Provided+credentials+could+not+be+validated",
                status_code=302,
            )
    except (ValueError, RuntimeError) as e:
        logger.error("Manual connect validation failed for %s: %s", provider, e)
        return RedirectResponse(
            url="/channels?error=Credential+validation+failed",
            status_code=302,
        )

    channel_svc = ChannelService(db)
    cred_svc = CredentialService()
    _store_channel_connection(
        db,
        channel_svc,
        cred_svc,
        provider=provider_enum,
        token_data=token_data,
        external_account_id=external_account_id,
    )
    db.commit()
    return RedirectResponse(
        url="/channels?success=Channel+connected+with+manual+token",
        status_code=302,
    )


@router.post("/{channel_id}/disconnect", response_model=None)
def disconnect_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Disconnect a channel — clear credentials and update status."""
    channel_svc = ChannelService(db)

    try:
        channel_svc.store_credentials(channel_id, None)
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
