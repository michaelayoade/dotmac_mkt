from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from app.adapters.base import ChannelAdapter, MetricData, PostData
from app.config import settings

logger = logging.getLogger(__name__)

GOOGLE_ADS_API = "https://googleads.googleapis.com/v16"
GOOGLE_OAUTH = "https://oauth2.googleapis.com/token"


class GoogleAdsAdapter(ChannelAdapter):
    """Adapter for Google Ads API."""

    def __init__(
        self, access_token: str, customer_id: str, developer_token: str = ""
    ) -> None:
        self.access_token = access_token
        self.customer_id = customer_id.replace("-", "")
        self.developer_token = developer_token or settings.google_ads_developer_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "developer-token": self.developer_token,
        }

    async def connect(
        self, auth_code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
        """Exchange Google OAuth auth code for tokens."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GOOGLE_OAUTH,
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "client_id": settings.google_ads_client_id,
                    "client_secret": settings.google_ads_client_secret,
                    "redirect_uri": redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("access_token", self.access_token)
            logger.info(
                "Google Ads OAuth token exchanged for customer %s", self.customer_id
            )
            return data

    async def refresh_token(self, refresh_token_value: str) -> dict | None:
        """Refresh an expired Google Ads OAuth token."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    GOOGLE_OAUTH,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token_value,
                        "client_id": settings.google_ads_client_id,
                        "client_secret": settings.google_ads_client_secret,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                self.access_token = data.get("access_token", self.access_token)
                logger.info("Google Ads token refreshed for customer %s", self.customer_id)
                return data
        except httpx.HTTPError as e:
            logger.warning("Google Ads token refresh failed: %s", e)
            return None

    async def disconnect(self) -> None:
        """Revoke the Google OAuth token (best-effort)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": self.access_token},
                )
                resp.raise_for_status()
                logger.info(
                    "Google Ads token revoked for customer %s", self.customer_id
                )
        except httpx.HTTPError as e:
            logger.warning("Google Ads disconnect failed: %s", e)

    async def validate_connection(self) -> bool:
        """List accessible customers to verify the token works."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{GOOGLE_ADS_API}/customers:listAccessibleCustomers",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Google Ads connection validation failed: %s", e)
            return False

    async def fetch_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        """Fetch campaign performance: impressions, clicks, spend, conversions."""
        # GAQL (Google Ads Query Language), not SQL — date values are safe ISO strings
        query = (
            "SELECT campaign.name, segments.date, "  # noqa: S608
            "metrics.impressions, metrics.clicks, "
            "metrics.cost_micros, metrics.conversions "
            "FROM campaign "
            f"WHERE segments.date BETWEEN '{start_date.isoformat()}' "
            f"AND '{end_date.isoformat()}'"
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{GOOGLE_ADS_API}/customers/{self.customer_id}"
                    "/googleAds:searchStream",
                    headers=self._headers(),
                    json={"query": query},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning("Google Ads fetch_analytics failed: %s", e)
            return []

        results: list[MetricData] = []
        for batch in data if isinstance(data, list) else [data]:
            for row in batch.get("results", []):
                segments = row.get("segments", {})
                metrics = row.get("metrics", {})
                try:
                    metric_date = date.fromisoformat(segments.get("date", ""))
                except (ValueError, TypeError):
                    metric_date = start_date

                for metric_name, key, transform in [
                    ("impressions", "impressions", float),
                    ("clicks", "clicks", float),
                    ("spend", "costMicros", lambda v: float(v) / 1_000_000),
                    ("conversions", "conversions", float),
                ]:
                    raw = metrics.get(key, 0)
                    results.append(
                        MetricData(
                            metric_date=metric_date,
                            metric_type=metric_name,
                            value=transform(raw),
                        )
                    )
        return results

    async def fetch_posts(
        self, since: datetime | None = None
    ) -> list[PostData]:
        """Google Ads does not have posts — return empty list."""
        return []
