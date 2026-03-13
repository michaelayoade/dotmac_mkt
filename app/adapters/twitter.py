from __future__ import annotations

import contextlib
import logging
from datetime import date, datetime

import httpx

from app.adapters.base import ChannelAdapter, MetricData, PostData
from app.config import settings

logger = logging.getLogger(__name__)

X_API = "https://api.twitter.com/2"


class TwitterAdapter(ChannelAdapter):
    """Adapter for X (Twitter) via API v2."""

    def __init__(self, access_token: str, account_id: str) -> None:
        self.access_token = access_token
        self.account_id = account_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def connect(self, auth_code: str) -> dict:
        """Exchange OAuth 2.0 PKCE auth code for an access token."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{X_API}/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "client_id": settings.twitter_client_id,
                    "redirect_uri": "",  # must match app config
                    "code_verifier": "",  # PKCE verifier — caller must supply
                },
                auth=(settings.twitter_client_id, settings.twitter_client_secret),
            )
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("access_token", self.access_token)
            logger.info("Twitter OAuth token exchanged for account %s", self.account_id)
            return data

    async def disconnect(self) -> None:
        """Revoke the access token (best-effort)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{X_API}/oauth2/revoke",
                    data={
                        "token": self.access_token,
                        "client_id": settings.twitter_client_id,
                    },
                    auth=(settings.twitter_client_id, settings.twitter_client_secret),
                )
                resp.raise_for_status()
                logger.info("Twitter token revoked for account %s", self.account_id)
        except httpx.HTTPError as e:
            logger.warning("Twitter disconnect failed: %s", e)

    async def validate_connection(self) -> bool:
        """Check whether the access token is valid."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{X_API}/users/me",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Twitter connection validation failed: %s", e)
            return False

    async def fetch_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        """Fetch tweet metrics: impressions, likes, retweets."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Get recent tweets for the user
                resp = await client.get(
                    f"{X_API}/users/{self.account_id}/tweets",
                    headers=self._headers(),
                    params={
                        "tweet.fields": "public_metrics,created_at",
                        "start_time": f"{start_date.isoformat()}T00:00:00Z",
                        "end_time": f"{end_date.isoformat()}T23:59:59Z",
                        "max_results": 100,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning("Twitter fetch_analytics failed: %s", e)
            return []

        results: list[MetricData] = []
        for tweet in data.get("data", []):
            metrics = tweet.get("public_metrics", {})
            created = tweet.get("created_at", "")
            try:
                metric_date = date.fromisoformat(created[:10])
            except (ValueError, TypeError):
                metric_date = start_date

            tweet_id = tweet.get("id", "")
            for metric_name, metric_key in [
                ("impressions", "impression_count"),
                ("likes", "like_count"),
                ("retweets", "retweet_count"),
            ]:
                value = metrics.get(metric_key, 0)
                results.append(
                    MetricData(
                        metric_date=metric_date,
                        metric_type=metric_name,
                        value=float(value),
                        post_id=tweet_id,
                    )
                )
        return results

    async def fetch_posts(
        self, since: datetime | None = None
    ) -> list[PostData]:
        """Fetch tweets from the user timeline."""
        params: dict[str, str] = {
            "tweet.fields": "created_at,text",
            "max_results": "100",
        }
        if since:
            params["start_time"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{X_API}/users/{self.account_id}/tweets",
                    headers=self._headers(),
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning("Twitter fetch_posts failed: %s", e)
            return []

        results: list[PostData] = []
        for tweet in data.get("data", []):
            published_at = None
            if tweet.get("created_at"):
                with contextlib.suppress(ValueError, TypeError):
                    published_at = datetime.fromisoformat(
                        tweet["created_at"].replace("Z", "+00:00")
                    )
            results.append(
                PostData(
                    external_id=tweet.get("id", ""),
                    title="",
                    content=tweet.get("text", ""),
                    published_at=published_at,
                )
            )
        return results
