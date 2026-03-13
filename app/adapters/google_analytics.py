from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from app.adapters.base import ChannelAdapter, MetricData, PostData
from app.config import settings

logger = logging.getLogger(__name__)

GA4_DATA_API = "https://analyticsdata.googleapis.com/v1beta"
GOOGLE_OAUTH = "https://oauth2.googleapis.com/token"


class GoogleAnalyticsAdapter(ChannelAdapter):
    """Adapter for Google Analytics 4 Data API."""

    def __init__(self, access_token: str, property_id: str) -> None:
        self.access_token = access_token
        self.property_id = property_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def connect(self, auth_code: str) -> dict:
        """Exchange Google OAuth auth code for tokens."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GOOGLE_OAUTH,
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "client_id": settings.google_analytics_client_id,
                    "client_secret": settings.google_analytics_client_secret,
                    "redirect_uri": "",  # must match app config
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("access_token", self.access_token)
            logger.info(
                "Google Analytics OAuth token exchanged for property %s",
                self.property_id,
            )
            return data

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
                    "Google Analytics token revoked for property %s",
                    self.property_id,
                )
        except httpx.HTTPError as e:
            logger.warning("Google Analytics disconnect failed: %s", e)

    async def validate_connection(self) -> bool:
        """Check property access by running a minimal metadata request."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{GA4_DATA_API}/properties/{self.property_id}/metadata",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Google Analytics connection validation failed: %s", e)
            return False

    async def fetch_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        """Fetch GA4 metrics: sessions, pageviews, users, bounce rate."""
        request_body = {
            "dateRanges": [
                {
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                }
            ],
            "dimensions": [{"name": "date"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "screenPageViews"},
                {"name": "totalUsers"},
                {"name": "bounceRate"},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{GA4_DATA_API}/properties/{self.property_id}:runReport",
                    headers=self._headers(),
                    json=request_body,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning("Google Analytics fetch_analytics failed: %s", e)
            return []

        metric_names = ["sessions", "pageviews", "users", "bounce_rate"]
        results: list[MetricData] = []

        for row in data.get("rows", []):
            dimensions = row.get("dimensionValues", [])
            metric_values = row.get("metricValues", [])

            # Date dimension is in YYYYMMDD format
            date_str = dimensions[0].get("value", "") if dimensions else ""
            try:
                metric_date = date(
                    int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8])
                )
            except (ValueError, IndexError):
                metric_date = start_date

            for i, name in enumerate(metric_names):
                if i < len(metric_values):
                    try:
                        value = float(metric_values[i].get("value", 0))
                    except (ValueError, TypeError):
                        value = 0.0
                    results.append(
                        MetricData(
                            metric_date=metric_date,
                            metric_type=name,
                            value=value,
                        )
                    )
        return results

    async def fetch_posts(
        self, since: datetime | None = None
    ) -> list[PostData]:
        """GA4 does not have posts — return empty list."""
        return []
