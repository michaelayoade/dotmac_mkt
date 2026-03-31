"""OAuth flow orchestration, credential storage, and channel connection lifecycle."""

from __future__ import annotations

import hashlib
import logging
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import urlencode
from uuid import UUID

import httpx
from itsdangerous import BadData, BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import get_adapter
from app.config import settings
from app.models.channel import Channel, ChannelProvider, ChannelStatus
from app.schemas.channel import ChannelCreate
from app.services.channel_integration_settings import get_meta_oauth_config
from app.services.channel_service import ChannelService
from app.services.credential_service import CredentialService
from app.services.marketing_runtime import get_marketing_value

logger = logging.getLogger(__name__)

# ── Provider configuration maps ──────────────────────────────────────────────

PROVIDER_KEY_MAP: dict[str, str] = {
    "meta_instagram": "account_id",
    "meta_facebook": "account_id",
    "meta_ads": "account_id",
    "twitter": "account_id",
    "linkedin": "organization_id",
    "linkedin_ads": "organization_id",
    "google_ads": "customer_id",
    "google_analytics": "property_id",
}

PROVIDER_LABELS: dict[str, str] = {
    "meta_instagram": "Instagram account ID",
    "meta_facebook": "Facebook page ID",
    "meta_ads": "Meta ad account ID",
    "twitter": "X account ID",
    "linkedin": "LinkedIn organization ID",
    "linkedin_ads": "LinkedIn ad account ID",
    "google_ads": "Google Ads customer ID",
    "google_analytics": "GA4 property ID",
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    provider.value: PROVIDER_LABELS.get(provider.value, "").replace(" ID", "")
    for provider in ChannelProvider
}

META_PROVIDER_VALUES = {
    ChannelProvider.meta_facebook.value,
    ChannelProvider.meta_instagram.value,
    ChannelProvider.meta_ads.value,
}

OAUTH_URLS: dict[str, str] = {
    "meta_instagram": "https://www.facebook.com/v19.0/dialog/oauth",
    "meta_facebook": "https://www.facebook.com/v19.0/dialog/oauth",
    "meta_ads": "https://www.facebook.com/v19.0/dialog/oauth",
    "twitter": "https://twitter.com/i/oauth2/authorize",
    "linkedin": "https://www.linkedin.com/oauth/v2/authorization",
    "linkedin_ads": "https://www.linkedin.com/oauth/v2/authorization",
    "google_ads": "https://accounts.google.com/o/oauth2/v2/auth",
    "google_analytics": "https://accounts.google.com/o/oauth2/v2/auth",
}

OAUTH_SCOPES: dict[str, str] = {
    "meta_instagram": "pages_show_list,pages_read_engagement,instagram_basic,instagram_manage_insights",
    "meta_facebook": "pages_show_list,pages_read_engagement",
    "meta_ads": "ads_read,business_management",
    "twitter": "tweet.read users.read offline.access",
    "linkedin": "r_liteprofile r_ads_reporting",
    "linkedin_ads": "r_liteprofile r_ads_reporting rw_ads",
    "google_ads": "https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.metadata.readonly",
    "google_analytics": "https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.metadata.readonly",
}

META_COMBINED_SCOPE = (
    "pages_show_list,pages_read_engagement,instagram_basic,"
    "instagram_manage_insights,ads_read,business_management"
)


class ChannelConnectionService:
    """Manages OAuth flows, credential storage, and channel connection lifecycle.

    Routes should handle HTTP request/response/cookies and delegate all
    business logic here.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._serializer = URLSafeTimedSerializer(settings.secret_key)
        self._channel_svc = ChannelService(db)
        self._cred_svc = CredentialService()

    # ── State tokens ─────────────────────────────────────────────────────

    def generate_state_token(
        self,
        *,
        provider: str,
        external_account_id: str | None = None,
        code_verifier: str | None = None,
    ) -> str:
        """Create a signed, time-limited state token for OAuth."""
        payload: dict[str, str] = {"provider": provider}
        if external_account_id:
            payload["external_account_id"] = external_account_id
        if code_verifier:
            payload["code_verifier"] = code_verifier
        return self._serializer.dumps(payload)

    def validate_state_token(self, state: str, *, max_age: int = 600) -> dict:
        """Validate and decode state token. Raises ValueError on failure."""
        try:
            return self._serializer.loads(state, max_age=max_age)
        except (BadSignature, SignatureExpired, BadData) as e:
            raise ValueError(f"Invalid or expired OAuth state token: {e}") from e

    # ── PKCE ─────────────────────────────────────────────────────────────

    @staticmethod
    def generate_pkce() -> tuple[str, str]:
        """Generate (code_verifier, code_challenge) for Twitter PKCE flow."""
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return code_verifier, code_challenge

    # ── OAuth URL construction ───────────────────────────────────────────

    def client_id_for_provider(self, provider: str) -> str:
        """Look up the OAuth client ID for a given provider."""
        if provider in META_PROVIDER_VALUES:
            return get_meta_oauth_config(self.db).app_id

        provider_keys = {
            "twitter": "twitter_client_id",
            "linkedin": "linkedin_client_id",
            "google_ads": "google_ads_client_id",
            "google_analytics": "google_analytics_client_id",
        }
        key = provider_keys.get(provider)
        return get_marketing_value(key) if key else ""

    def build_oauth_url(
        self,
        provider: str,
        *,
        callback_url: str,
        external_account_id: str | None = None,
    ) -> tuple[str, str]:
        """Build OAuth redirect URL and state token.

        Returns (redirect_url, state_token).
        Raises ValueError if provider not configured.
        """
        oauth_url = OAUTH_URLS.get(provider)
        client_id = self.client_id_for_provider(provider)
        scopes = OAUTH_SCOPES.get(provider, "")

        if not oauth_url or not client_id:
            raise ValueError(f"Provider {provider} is not configured")

        state_payload_kwargs: dict[str, str | None] = {
            "provider": provider,
            "external_account_id": external_account_id,
        }

        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": callback_url,
            "scope": scopes,
            "response_type": "code",
        }

        code_verifier: str | None = None
        if provider == "twitter":
            code_verifier, code_challenge = self.generate_pkce()
            state_payload_kwargs["code_verifier"] = code_verifier
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        state = self.generate_state_token(**state_payload_kwargs)
        params["state"] = state

        redirect_url = f"{oauth_url}?{urlencode(params)}"
        return redirect_url, state

    def build_meta_oauth_url(self, *, callback_url: str) -> tuple[str, str]:
        """Build Meta-specific OAuth URL with combined scopes.

        Returns (redirect_url, state_token).
        Raises ValueError if Meta app credentials not configured.
        """
        meta_config = get_meta_oauth_config(self.db)
        if not meta_config.app_id or not meta_config.app_secret:
            raise ValueError("Meta App credentials are required")

        state = self.generate_state_token(provider="meta")
        params = {
            "client_id": meta_config.app_id,
            "redirect_uri": callback_url,
            "scope": META_COMBINED_SCOPE,
            "response_type": "code",
            "state": state,
        }
        redirect_url = (
            f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"
        )
        return redirect_url, state

    # ── Token exchange ───────────────────────────────────────────────────

    async def exchange_code(
        self,
        provider: str,
        *,
        code: str,
        callback_url: str,
        code_verifier: str | None = None,
    ) -> dict:
        """Exchange authorization code for tokens via adapter.

        Returns token dict from adapter.connect().
        Raises ValueError/RuntimeError on failure.
        """
        try:
            provider_enum = ChannelProvider(provider)
        except ValueError as e:
            raise ValueError(f"Unknown provider: {provider}") from e

        adapter_kwargs: dict[str, str] = {"access_token": ""}
        extra_key = PROVIDER_KEY_MAP.get(provider, "account_id")
        adapter_kwargs[extra_key] = ""

        adapter = get_adapter(provider_enum, **adapter_kwargs)
        return await adapter.connect(
            code, redirect_uri=callback_url, code_verifier=code_verifier
        )

    async def exchange_meta_code(self, *, code: str, callback_url: str) -> dict:
        """Exchange Meta OAuth code using Meta-specific adapter config."""
        meta_config = get_meta_oauth_config(self.db)
        adapter = get_adapter(
            ChannelProvider.meta_facebook,
            access_token="",
            account_id="",
            client_id=meta_config.app_id,
            client_secret=meta_config.app_secret,
            graph_version=meta_config.graph_version,
            timeout_seconds=meta_config.api_timeout_seconds,
        )
        return await adapter.connect(code, redirect_uri=callback_url)

    # ── Credential storage ───────────────────────────────────────────────

    @staticmethod
    def extract_external_account_id(
        provider: str,
        token_data: dict,
        requested_id: str | None,
        existing_id: str | None,
    ) -> str:
        """Extract external account ID from multiple sources."""
        provider_key = PROVIDER_KEY_MAP.get(provider, "account_id")
        candidates = (
            token_data.get(provider_key),
            token_data.get("external_account_id"),
            requested_id,
            existing_id,
        )
        for candidate in candidates:
            if isinstance(candidate, str):
                value = candidate.strip()
                if value:
                    return value
        return ""

    @staticmethod
    def merge_token_data(
        provider: str, token_data: dict, external_account_id: str
    ) -> dict:
        """Merge external account ID into token data."""
        merged = dict(token_data)
        merged["external_account_id"] = external_account_id
        merged[PROVIDER_KEY_MAP.get(provider, "account_id")] = external_account_id
        return merged

    def store_connection(
        self,
        *,
        provider: ChannelProvider,
        token_data: dict,
        external_account_id: str,
        name: str | None = None,
    ) -> Channel:
        """Encrypt tokens and store on channel. Finds or creates the channel."""
        channel = self._get_or_create_channel(provider, external_account_id, name=name)
        enriched = self.merge_token_data(
            provider.value, token_data, external_account_id
        )
        encrypted = self._cred_svc.encrypt(enriched)
        self._channel_svc.store_credentials(channel.id, encrypted)
        self._channel_svc.update_external_account_id(channel.id, external_account_id)
        self._channel_svc.update_status(channel.id, ChannelStatus.connected)
        self._channel_svc.update_last_synced(channel.id)
        return channel

    def disconnect(self, channel_id: UUID) -> None:
        """Clear credentials and set status to disconnected."""
        self._channel_svc.store_credentials(channel_id, None)
        self._channel_svc.update_status(channel_id, ChannelStatus.disconnected)
        logger.info("Disconnected channel %s", channel_id)

    # ── Meta asset discovery ─────────────────────────────────────────────

    async def discover_meta_assets(self, access_token: str) -> list[dict[str, str]]:
        """Discover Facebook pages, Instagram accounts, and ad accounts.

        Returns list of dicts with keys: provider, external_account_id, name, access_token.
        """
        meta_config = get_meta_oauth_config(self.db)
        graph_api = f"https://graph.facebook.com/{meta_config.graph_version}"
        timeout = meta_config.api_timeout_seconds

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
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
            async with httpx.AsyncClient(timeout=timeout) as client:
                ad_resp = await client.get(
                    f"{graph_api}/me/adaccounts",
                    params={
                        "fields": "id,account_id,name,account_status,currency",
                        "access_token": access_token,
                    },
                )
                ad_resp.raise_for_status()
                ad_accounts_data = ad_resp.json()
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
            raw_id = str(account.get("account_id") or account.get("id") or "").strip()
            if not raw_id:
                continue
            assets.append(
                {
                    "provider": ChannelProvider.meta_ads.value,
                    "external_account_id": raw_id.removeprefix("act_"),
                    "name": str(account.get("name", "")).strip() or "Meta Ad Account",
                    "access_token": access_token,
                }
            )
        return assets

    # ── Manual token connection ──────────────────────────────────────────

    async def manual_connect(
        self,
        *,
        provider_str: str,
        access_token: str,
        refresh_token: str | None,
        external_account_id: str,
    ) -> Channel:
        """Validate credentials and store a manually-provided token.

        Raises ValueError if validation fails.
        """
        provider_enum = self.resolve_manual_provider(provider_str, external_account_id)
        adapter_kwargs: dict[str, str] = {"access_token": access_token}
        extra_key = PROVIDER_KEY_MAP.get(provider_enum.value, "account_id")
        adapter_kwargs[extra_key] = external_account_id

        adapter = get_adapter(provider_enum, **adapter_kwargs)
        if not await adapter.validate_connection():
            raise ValueError(
                "Token validation failed — check credentials and try again"
            )

        token_data: dict[str, str] = {
            "access_token": access_token,
            "manual_token": "true",
            extra_key: external_account_id,
        }
        if refresh_token:
            token_data["refresh_token"] = refresh_token

        return self.store_connection(
            provider=provider_enum,
            token_data=token_data,
            external_account_id=external_account_id,
        )

    def resolve_manual_provider(
        self, provider: str, external_account_id: str
    ) -> ChannelProvider:
        """Resolve 'meta' shorthand to meta_facebook or meta_instagram."""
        if provider != "meta":
            return ChannelProvider(provider)

        account_id = external_account_id.strip()
        if account_id:
            existing = self.db.scalar(
                select(Channel.provider).where(
                    Channel.provider.in_(
                        [ChannelProvider.meta_facebook, ChannelProvider.meta_instagram]
                    ),
                    Channel.external_account_id == account_id,
                )
            )
            if existing is not None:
                return existing

        if account_id.startswith("1784") or len(account_id) >= 16:
            return ChannelProvider.meta_instagram
        return ChannelProvider.meta_facebook

    # ── Channel provisioning ─────────────────────────────────────────────

    def ensure_default_channels(self) -> list[Channel]:
        """Create placeholder Channel rows for all ChannelProvider values if missing."""
        existing = list(self.db.scalars(select(Channel).order_by(Channel.name)).all())
        existing_by_provider = {channel.provider for channel in existing}
        created = False

        for provider in ChannelProvider:
            if provider in existing_by_provider:
                continue
            self._channel_svc.create(
                ChannelCreate(
                    name=PROVIDER_DISPLAY_NAMES.get(
                        provider.value, provider.value.replace("_", " ").title()
                    ),
                    provider=provider,
                )
            )
            created = True

        if created:
            self.db.commit()
            existing = list(
                self.db.scalars(select(Channel).order_by(Channel.name)).all()
            )

        return existing

    # ── Private helpers ──────────────────────────────────────────────────

    def _get_or_create_channel(
        self,
        provider: ChannelProvider,
        external_account_id: str,
        name: str | None = None,
    ) -> Channel:
        """Find existing channel by provider+external_account_id or create one."""
        if external_account_id:
            channel = self.db.scalar(
                select(Channel).where(
                    Channel.provider == provider,
                    Channel.external_account_id == external_account_id,
                )
            )
            if channel is not None:
                if name:
                    channel.name = name
                    self.db.flush()
                return channel

        channel = self.db.scalar(
            select(Channel).where(
                Channel.provider == provider,
                Channel.external_account_id.is_(None),
            )
        )
        if channel is not None:
            channel.external_account_id = (
                external_account_id or channel.external_account_id
            )
            if name:
                channel.name = name
            self.db.flush()
            return channel

        return self._channel_svc.create(
            ChannelCreate(
                name=name
                or PROVIDER_DISPLAY_NAMES.get(
                    provider.value, provider.value.replace("_", " ").title()
                ),
                provider=provider,
            )
        )
