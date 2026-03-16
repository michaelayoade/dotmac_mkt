from __future__ import annotations

import contextlib
import logging
from datetime import UTC, date, datetime

import httpx

from app.adapters.base import ChannelAdapter, MetricData, PostData
from app.config import settings

logger = logging.getLogger(__name__)

LINKEDIN_API = "https://api.linkedin.com/v2"
LINKEDIN_OAUTH = "https://www.linkedin.com/oauth/v2"


class LinkedInAdapter(ChannelAdapter):
    """Adapter for LinkedIn Marketing API."""

    def __init__(self, access_token: str, organization_id: str) -> None:
        self.access_token = access_token
        self.organization_id = organization_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    async def connect(
        self, auth_code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
        """Exchange auth code for an access token."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{LINKEDIN_OAUTH}/accessToken",
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("access_token", self.access_token)
            logger.info(
                "LinkedIn OAuth token exchanged for org %s", self.organization_id
            )
            return data

    async def refresh_token(self, refresh_token_value: str) -> dict | None:
        """Refresh an expired LinkedIn OAuth token."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{LINKEDIN_OAUTH}/accessToken",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token_value,
                        "client_id": settings.linkedin_client_id,
                        "client_secret": settings.linkedin_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                data = resp.json()
                self.access_token = data.get("access_token", self.access_token)
                logger.info("LinkedIn token refreshed for org %s", self.organization_id)
                return data
        except httpx.HTTPError as e:
            logger.warning("LinkedIn token refresh failed: %s", e)
            return None

    async def disconnect(self) -> None:
        """LinkedIn does not support programmatic token revocation.

        Tokens expire naturally. Log the intent for audit.
        """
        logger.info(
            "LinkedIn disconnect requested for org %s — tokens will expire naturally",
            self.organization_id,
        )

    async def validate_connection(self) -> bool:
        """Check whether the access token is valid."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LINKEDIN_API}/me",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("LinkedIn connection validation failed: %s", e)
            return False

    async def fetch_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        """Fetch organization page statistics."""
        start_ms = int(
            datetime.combine(start_date, datetime.min.time()).timestamp() * 1000
        )
        end_ms = int(datetime.combine(end_date, datetime.min.time()).timestamp() * 1000)
        urn = f"urn:li:organization:{self.organization_id}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{LINKEDIN_API}/organizationalEntityShareStatistics",
                    headers=self._headers(),
                    params={
                        "q": "organizationalEntity",
                        "organizationalEntity": urn,
                        "timeIntervals.timeGranularityType": "DAY",
                        "timeIntervals.timeRange.start": str(start_ms),
                        "timeIntervals.timeRange.end": str(end_ms),
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning("LinkedIn fetch_analytics failed: %s", e)
            return []

        results: list[MetricData] = []
        for element in data.get("elements", []):
            stats = element.get("totalShareStatistics", {})
            time_range = element.get("timeRange", {})
            try:
                metric_date = date.fromtimestamp(time_range.get("start", 0) / 1000)
            except (ValueError, TypeError, OSError):
                metric_date = start_date

            for metric_name, key in [
                ("impressions", "impressionCount"),
                ("clicks", "clickCount"),
                ("engagement", "engagement"),
                ("likes", "likeCount"),
                ("shares", "shareCount"),
            ]:
                value = stats.get(key, 0)
                if value:
                    results.append(
                        MetricData(
                            metric_date=metric_date,
                            metric_type=metric_name,
                            value=float(value),
                        )
                    )
        return results

    async def fetch_posts(self, since: datetime | None = None) -> list[PostData]:
        """Fetch organization shares/posts."""
        urn = f"urn:li:organization:{self.organization_id}"
        params: dict[str, str] = {
            "q": "owners",
            "owners": urn,
            "sortBy": "LAST_MODIFIED",
            "count": "50",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{LINKEDIN_API}/shares",
                    headers=self._headers(),
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning("LinkedIn fetch_posts failed: %s", e)
            return []

        results: list[PostData] = []
        for item in data.get("elements", []):
            created_ms = item.get("created", {}).get("time", 0)
            published_at = None
            if created_ms:
                with contextlib.suppress(ValueError, TypeError, OSError):
                    published_at = datetime.fromtimestamp(created_ms / 1000, tz=UTC)

            if since and published_at and published_at < since:
                continue

            text_content = item.get("text", {}).get("text", "") or item.get(
                "specificContent", {}
            ).get("com.linkedin.ugc.ShareContent", {}).get("shareCommentary", {}).get(
                "text", ""
            )
            results.append(
                PostData(
                    external_id=item.get("id", ""),
                    title="",
                    content=text_content,
                    published_at=published_at,
                )
            )
        return results
