from __future__ import annotations

import contextlib
import logging
from datetime import date, datetime

import httpx

from app.adapters.base import (
    ChannelAdapter,
    MetricData,
    PostData,
    PublishResult,
    UpdateResult,
)
from app.config import settings

logger = logging.getLogger(__name__)

X_API = "https://api.twitter.com/2"


class TwitterAdapter(ChannelAdapter):
    """Adapter for X (Twitter) via API v2."""

    supports_remote_update = True
    supports_remote_delete = True

    def __init__(self, access_token: str, account_id: str) -> None:
        self.access_token = access_token
        self.account_id = account_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def connect(
        self, auth_code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
        """Exchange OAuth 2.0 PKCE auth code for an access token."""
        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": settings.twitter_client_id,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{X_API}/oauth2/token",
                data=data,
                auth=(settings.twitter_client_id, settings.twitter_client_secret),
            )
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("access_token", self.access_token)
            logger.info("Twitter OAuth token exchanged for account %s", self.account_id)
            return data

    async def refresh_token(self, refresh_token_value: str) -> dict | None:
        """Refresh an expired Twitter OAuth 2.0 token."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{X_API}/oauth2/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token_value,
                        "client_id": settings.twitter_client_id,
                    },
                    auth=(settings.twitter_client_id, settings.twitter_client_secret),
                )
                resp.raise_for_status()
                data = resp.json()
                self.access_token = data.get("access_token", self.access_token)
                logger.info("Twitter token refreshed for account %s", self.account_id)
                return data
        except httpx.HTTPError as e:
            logger.warning("Twitter token refresh failed: %s", e)
            return None

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

    async def publish_post(
        self,
        content: str,
        *,
        media_urls: list[str] | None = None,
        title: str | None = None,
    ) -> PublishResult:
        """Publish a tweet."""
        payload: dict[str, object] = {"text": content}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{X_API}/tweets",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            tweet_id = resp.json().get("data", {}).get("id", "")
        logger.info("Published tweet %s for account %s", tweet_id, self.account_id)
        return PublishResult(
            external_post_id=tweet_id,
            url=f"https://x.com/i/status/{tweet_id}" if tweet_id else None,
        )

    async def update_post(
        self,
        external_post_id: str,
        content: str,
        *,
        media_urls: list[str] | None = None,
        title: str | None = None,
    ) -> UpdateResult:
        """Edit a post within X's edit window."""
        payload: dict[str, object] = {
            "text": content,
            "edit_options": {"previous_post_id": external_post_id},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{X_API}/tweets",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            updated_id = resp.json().get("data", {}).get("id", "")
        logger.info(
            "Updated tweet %s -> %s for account %s",
            external_post_id,
            updated_id,
            self.account_id,
        )
        return UpdateResult(
            external_post_id=updated_id or external_post_id,
            url=f"https://x.com/i/status/{updated_id}" if updated_id else None,
        )

    async def delete_post(self, external_post_id: str) -> None:
        """Delete a published post."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{X_API}/tweets/{external_post_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
        logger.info(
            "Deleted tweet %s for account %s",
            external_post_id,
            self.account_id,
        )

    async def fetch_posts(self, since: datetime | None = None) -> list[PostData]:
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
