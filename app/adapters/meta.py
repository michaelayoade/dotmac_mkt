from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, date, datetime

import httpx

from app.adapters.base import (
    ChannelAdapter,
    MetricData,
    PostData,
    PublishResult,
    UpdateResult,
)
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

    @property
    def supports_remote_update(self) -> bool:
        return self.provider == ChannelProvider.meta_facebook

    @property
    def supports_remote_delete(self) -> bool:
        return self.provider == ChannelProvider.meta_facebook

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    @staticmethod
    def _error_message(exc: httpx.HTTPStatusError) -> str:
        message = str(exc)
        with contextlib.suppress(ValueError, TypeError, AttributeError):
            payload = exc.response.json()
            error = payload.get("error") or {}
            remote_message = error.get("message")
            if remote_message:
                return str(remote_message)
        return message

    def _analytics_metrics(self) -> list[tuple[str, str]]:
        if self.provider == ChannelProvider.meta_instagram:
            return [
                ("views", "impressions"),
                ("reach", "reach"),
            ]
        return []

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
        results = await self._fetch_account_analytics(start_date, end_date)
        results.extend(await self._fetch_post_analytics(start_date, end_date))
        return results

    async def _fetch_account_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        results: list[MetricData] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for remote_metric, local_metric in self._analytics_metrics():
                try:
                    params = {
                        "metric": remote_metric,
                        "period": "day",
                        "since": start_date.isoformat(),
                        "until": end_date.isoformat(),
                    }
                    if (
                        self.provider == ChannelProvider.meta_instagram
                        and remote_metric == "views"
                    ):
                        params["metric_type"] = "total_value"
                    resp = await client.get(
                        f"{self.graph_api}/{self.account_id}/insights",
                        headers=self._headers(),
                        params=params,
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

    async def _fetch_post_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        metric_map = (
            [
                ("views", "impressions"),
                ("reach", "reach"),
                ("total_interactions", "engagement"),
            ]
            if self.provider == ChannelProvider.meta_instagram
            else [
                ("post_impressions_unique", "reach"),
                ("post_clicks", "clicks"),
                ("post_reactions_by_type_total", "engagement"),
            ]
        )

        posts = await self.fetch_posts()
        results: list[MetricData] = []

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for post in posts:
                if not post.external_id:
                    continue

                try:
                    resp = await client.get(
                        f"{self.graph_api}/{post.external_id}/insights",
                        headers=self._headers(),
                        params={"metric": ",".join(name for name, _ in metric_map)},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as e:
                    logger.warning(
                        "Meta fetch_post_analytics failed for %s post %s: %s",
                        self.account_id,
                        post.external_id,
                        e,
                    )
                    continue

                for metric_block in data.get("data", []):
                    raw_value = metric_block.get("values", [{}])
                    raw_value = raw_value[0].get("value", 0) if raw_value else 0
                    if isinstance(raw_value, dict):
                        raw_value = sum(
                            float(v)
                            for v in raw_value.values()
                            if isinstance(v, int | float)
                        )
                    local_metric = next(
                        (
                            local_name
                            for remote_name, local_name in metric_map
                            if remote_name == metric_block.get("name")
                        ),
                        None,
                    )
                    if local_metric is None:
                        continue
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    results.append(
                        MetricData(
                            metric_date=end_date,
                            metric_type=local_metric,
                            value=value,
                            post_id=post.external_id,
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
        """Publish a post to Facebook (feed) or Instagram (media)."""
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            if self.provider == ChannelProvider.meta_instagram:
                # Instagram Container-based publish (text/carousel not supported
                # without media — post as caption on first media URL or raise)
                if not media_urls:
                    raise ValueError("Instagram requires at least one media URL")
                # Step 1: create media container
                try:
                    resp = await client.post(
                        f"{self.graph_api}/{self.account_id}/media",
                        headers=self._headers(),
                        data={
                            "image_url": media_urls[0],
                            "caption": content,
                        },
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ValueError(
                        f"Instagram publish failed: {self._error_message(exc)}"
                    ) from exc
                container_id = resp.json().get("id")
                # Step 2: publish the container
                try:
                    resp = await client.post(
                        f"{self.graph_api}/{self.account_id}/media_publish",
                        headers=self._headers(),
                        data={"creation_id": container_id},
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ValueError(
                        f"Instagram publish failed: {self._error_message(exc)}"
                    ) from exc
                publish_id = resp.json().get("id", "")
                post_id, permalink = await self._resolve_instagram_publish_result(
                    client, publish_id, content
                )
            else:
                # Facebook Page post
                data: dict[str, str] = {"message": content}
                if media_urls:
                    data["link"] = media_urls[0]
                resp = await client.post(
                    f"{self.graph_api}/{self.account_id}/feed",
                    headers=self._headers(),
                    data=data,
                )
                resp.raise_for_status()
                post_id = resp.json().get("id", "")
                permalink = None

        logger.info("Published post %s to Meta account %s", post_id, self.account_id)
        return PublishResult(external_post_id=post_id, url=permalink)

    async def _resolve_instagram_publish_result(
        self, client: httpx.AsyncClient, publish_id: str, content: str
    ) -> tuple[str, str | None]:
        for _attempt in range(3):
            media = await self._fetch_instagram_media(client, publish_id)
            if media is not None:
                return media["id"], media.get("permalink")

            matched_media = await self._find_instagram_media_by_caption(client, content)
            if matched_media is not None:
                return matched_media["id"], matched_media.get("permalink")

            await asyncio.sleep(1)

        raise ValueError(
            "Instagram publish failed to resolve a live media object after publish."
        )

    async def _fetch_instagram_media(
        self, client: httpx.AsyncClient, media_id: str
    ) -> dict | None:
        if not media_id:
            return None
        try:
            resp = await client.get(
                f"{self.graph_api}/{media_id}",
                headers=self._headers(),
                params={"fields": "id,caption,timestamp,permalink"},
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        data = resp.json()
        if not data.get("id"):
            return None
        return data

    async def _find_instagram_media_by_caption(
        self, client: httpx.AsyncClient, content: str
    ) -> dict | None:
        try:
            resp = await client.get(
                f"{self.graph_api}/{self.account_id}/media",
                headers=self._headers(),
                params={
                    "fields": "id,caption,timestamp,permalink",
                    "limit": 25,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return None

        normalized_content = (content or "").strip()
        matches = [
            item
            for item in resp.json().get("data", [])
            if (item.get("caption") or "").strip() == normalized_content
            and item.get("id")
        ]
        if not matches:
            return None
        matches.sort(
            key=lambda item: (
                item.get("timestamp") or datetime.min.replace(tzinfo=UTC).isoformat()
            ),
            reverse=True,
        )
        return matches[0]

    async def update_post(
        self,
        external_post_id: str,
        content: str,
        *,
        media_urls: list[str] | None = None,
        title: str | None = None,
    ) -> UpdateResult:
        """Update a Facebook Page feed post message."""
        if self.provider != ChannelProvider.meta_facebook:
            raise NotImplementedError("Remote post updates are not supported")

        if title:
            logger.debug(
                "Ignoring title update for Meta post %s; Meta updates only support message edits",
                external_post_id,
            )
        if media_urls:
            logger.debug(
                "Ignoring media update for Meta post %s; attachment edits are not supported",
                external_post_id,
            )

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                resp = await client.post(
                    f"{self.graph_api}/{external_post_id}",
                    headers=self._headers(),
                    data={"message": content},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ValueError(
                    f"Facebook post update failed: {self._error_message(exc)}"
                ) from exc

        logger.info(
            "Updated Meta post %s for account %s", external_post_id, self.account_id
        )
        return UpdateResult(external_post_id=external_post_id)

    async def delete_post(self, external_post_id: str) -> None:
        """Delete a Facebook Page feed post."""
        if self.provider != ChannelProvider.meta_facebook:
            raise NotImplementedError("Remote post deletion is not supported")

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                resp = await client.delete(
                    f"{self.graph_api}/{external_post_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ValueError(
                    f"Facebook post deletion failed: {self._error_message(exc)}"
                ) from exc

        logger.info(
            "Deleted Meta post %s for account %s", external_post_id, self.account_id
        )

    async def fetch_posts(self, since: datetime | None = None) -> list[PostData]:
        """Fetch media/feed posts from the account."""
        params: dict[str, str]
        if self.provider == ChannelProvider.meta_instagram:
            params = {"fields": "id,caption,timestamp"}
        else:
            params = {"fields": "id,message,created_time"}
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
            created_value = item.get("timestamp") or item.get("created_time")
            if created_value:
                with contextlib.suppress(ValueError, TypeError):
                    published_at = datetime.fromisoformat(
                        str(created_value).replace("Z", "+00:00")
                    )
            results.append(
                PostData(
                    external_id=item.get("id", ""),
                    title="",
                    content=item.get("caption", "") or item.get("message", ""),
                    published_at=published_at,
                )
            )
        return results
