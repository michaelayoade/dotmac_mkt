from __future__ import annotations

import contextlib
import logging
from datetime import date, datetime

import httpx

from app.adapters.base import ChannelAdapter, MetricData, PostData
from app.config import settings
from app.models.channel import ChannelProvider

logger = logging.getLogger(__name__)


class MetaAdapter(ChannelAdapter):
    """Adapter for Instagram and Facebook via Meta Graph API v19."""

    def __init__(
        self,
        access_token: str,
        account_id: str,
        provider: ChannelProvider | str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        graph_version: str = "v19.0",
        timeout_seconds: int = 30,
    ) -> None:
        self.access_token = access_token
        self.account_id = account_id
        self.provider = (
            (
                provider
                if isinstance(provider, ChannelProvider)
                else ChannelProvider(provider)
            )
            if provider
            else None
        )
        self.client_id = client_id or settings.meta_app_id
        self.client_secret = client_secret or settings.meta_app_secret
        self.graph_version = graph_version
        self.timeout_seconds = timeout_seconds

    @property
    def graph_api(self) -> str:
        return f"https://graph.facebook.com/{self.graph_version}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _analytics_metrics(self) -> list[tuple[str, str]]:
        if self.provider == ChannelProvider.meta_instagram:
            return [
                ("views", "impressions"),
                ("reach", "reach"),
                ("total_interactions", "engagement"),
            ]
        return [
            ("page_impressions", "impressions"),
            ("page_impressions_unique", "reach"),
            ("page_post_engagements", "engagement"),
        ]

    async def connect(
        self, auth_code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
        """Exchange auth code for a long-lived access token."""
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(
                f"{self.graph_api}/oauth/access_token",
                params={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": auth_code,
                    "redirect_uri": redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("access_token", self.access_token)
            logger.info("Meta OAuth token exchanged for account %s", self.account_id)
            return data

    async def refresh_token(self, refresh_token_value: str) -> dict | None:
        """Exchange a long-lived token for a new one (Meta token refresh)."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(
                    f"{self.graph_api}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "fb_exchange_token": refresh_token_value,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                self.access_token = data.get("access_token", self.access_token)
                logger.info("Meta token refreshed for account %s", self.account_id)
                return data
        except httpx.HTTPError as e:
            logger.warning("Meta token refresh failed: %s", e)
            return None

    async def disconnect(self) -> None:
        """Revoke permissions (best-effort)."""
        try:
            async with httpx.AsyncClient(
                timeout=min(self.timeout_seconds, 15)
            ) as client:
                resp = await client.delete(
                    f"{self.graph_api}/me/permissions",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                logger.info("Meta permissions revoked for account %s", self.account_id)
        except httpx.HTTPError as e:
            logger.warning("Meta disconnect failed: %s", e)

    async def validate_connection(self) -> bool:
        """Check whether the access token is still valid."""
        try:
            async with httpx.AsyncClient(
                timeout=min(self.timeout_seconds, 15)
            ) as client:
                resp = await client.get(
                    f"{self.graph_api}/me",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Meta connection validation failed: %s", e)
            return False

    async def fetch_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        results: list[MetricData] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for remote_metric, local_metric in self._analytics_metrics():
                try:
                    resp = await client.get(
                        f"{self.graph_api}/{self.account_id}/insights",
                        headers=self._headers(),
                        params={
                            "metric": remote_metric,
                            "period": "day",
                            "since": start_date.isoformat(),
                            "until": end_date.isoformat(),
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as e:
                    logger.warning(
                        "Meta fetch_analytics failed for %s metric %s: %s",
                        self.account_id,
                        remote_metric,
                        e,
                    )
                    continue

                for metric_block in data.get("data", []):
                    for value_entry in metric_block.get("values", []):
                        raw_value = value_entry.get("value", 0)
                        if isinstance(raw_value, dict):
                            logger.warning(
                                "Skipping non-scalar metric value for %s metric %s",
                                self.account_id,
                                remote_metric,
                            )
                            continue
                        try:
                            results.append(
                                MetricData(
                                    metric_date=date.fromisoformat(
                                        value_entry["end_time"][:10]
                                    ),
                                    metric_type=local_metric,
                                    value=float(raw_value),
                                )
                            )
                        except (KeyError, ValueError, TypeError) as e:
                            logger.warning(
                                "Skipping malformed metric entry for %s metric %s: %s",
                                self.account_id,
                                remote_metric,
                                e,
                            )
        return results

    async def fetch_posts(self, since: datetime | None = None) -> list[PostData]:
        """Fetch media/feed posts from the account."""
        params: dict[str, str] = {"fields": "id,message,created_time"}
        if since:
            params["since"] = str(int(since.timestamp()))

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                # Try /media first (Instagram), fall back to /feed (Facebook)
                resp = await client.get(
                    f"{self.graph_api}/{self.account_id}/media",
                    headers=self._headers(),
                    params=params,
                )
                if resp.status_code != 200:
                    resp = await client.get(
                        f"{self.graph_api}/{self.account_id}/feed",
                        headers=self._headers(),
                        params=params,
                    )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning("Meta fetch_posts failed: %s", e)
            return []

        results: list[PostData] = []
        for item in data.get("data", []):
            published_at = None
            if item.get("created_time"):
                with contextlib.suppress(ValueError, TypeError):
                    published_at = datetime.fromisoformat(
                        item["created_time"].replace("Z", "+00:00")
                    )
            results.append(
                PostData(
                    external_id=item.get("id", ""),
                    title="",
                    content=item.get("message", ""),
                    published_at=published_at,
                )
            )
        return results
