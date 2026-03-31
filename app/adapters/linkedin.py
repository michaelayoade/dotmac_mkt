from __future__ import annotations

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

logger = logging.getLogger(__name__)

LINKEDIN_API = "https://api.linkedin.com/v2"
LINKEDIN_OAUTH = "https://www.linkedin.com/oauth/v2"


class LinkedInAdapter(ChannelAdapter):
    """Adapter for LinkedIn Marketing API."""

    supports_remote_update = True
    supports_remote_delete = True

    def __init__(self, access_token: str, organization_id: str) -> None:
        self.access_token = access_token
        self.organization_id = organization_id

    def _headers(self, *, versioned: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if versioned:
            headers["Linkedin-Version"] = "202511"
        return headers

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
        results = await self._fetch_organization_analytics(start_date, end_date)
        results.extend(await self._fetch_post_analytics(start_date, end_date))
        return results

    async def _fetch_organization_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
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

    async def _fetch_post_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        posts = await self.fetch_posts()
        if not posts:
            return []

        urn = f"urn:li:organization:{self.organization_id}"
        results: list[MetricData] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for post in posts:
                if not post.external_id:
                    continue

                post_urn = (
                    post.external_id
                    if post.external_id.startswith("urn:")
                    else f"urn:li:share:{post.external_id}"
                )
                try:
                    resp = await client.get(
                        f"{LINKEDIN_API}/organizationalEntityShareStatistics",
                        headers=self._headers(),
                        params={
                            "q": "organizationalEntity",
                            "organizationalEntity": urn,
                            "shares[0]": post_urn,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as e:
                    logger.warning(
                        "LinkedIn fetch_post_analytics failed for %s post %s: %s",
                        self.organization_id,
                        post.external_id,
                        e,
                    )
                    continue

                for element in data.get("elements", []):
                    stats = element.get("totalShareStatistics", {})
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
                                    metric_date=end_date,
                                    metric_type=metric_name,
                                    value=float(value),
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
        """Publish a share to a LinkedIn organization page."""
        urn = f"urn:li:organization:{self.organization_id}"
        payload = {
            "author": urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{LINKEDIN_API}/ugcPosts",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            post_id = resp.json().get("id", "")
        logger.info(
            "Published LinkedIn post %s for org %s", post_id, self.organization_id
        )
        return PublishResult(external_post_id=post_id)

    async def update_post(
        self,
        external_post_id: str,
        content: str,
        *,
        media_urls: list[str] | None = None,
        title: str | None = None,
    ) -> UpdateResult:
        """Update post commentary for a previously published organization post."""
        encoded_post_id = external_post_id.replace(":", "%3A")
        payload = {"patch": {"$set": {"commentary": content}}}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.linkedin.com/rest/posts/{encoded_post_id}",
                headers={
                    **self._headers(versioned=True),
                    "Content-Type": "application/json",
                    "X-RestLi-Method": "PARTIAL_UPDATE",
                },
                json=payload,
            )
            resp.raise_for_status()
        logger.info(
            "Updated LinkedIn post %s for org %s",
            external_post_id,
            self.organization_id,
        )
        return UpdateResult(external_post_id=external_post_id)

    async def delete_post(self, external_post_id: str) -> None:
        """Delete a previously published organization post."""
        encoded_post_id = external_post_id.replace(":", "%3A")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"https://api.linkedin.com/rest/posts/{encoded_post_id}",
                headers={
                    **self._headers(versioned=True),
                    "X-RestLi-Method": "DELETE",
                },
            )
            resp.raise_for_status()
        logger.info(
            "Deleted LinkedIn post %s for org %s",
            external_post_id,
            self.organization_id,
        )

    async def fetch_ads_history(
        self, start_date: date, end_date: date
    ) -> list[dict[str, str | float]]:
        """Fetch LinkedIn Campaign Manager ad hierarchy and analytics.

        Returns flat dicts normalised for AdSyncService:
        campaign_group_id, campaign_group_name, campaign_id, campaign_name,
        creative_id, creative_name, date_start, impressions, clicks, spend, conversions.
        """
        account_urn = f"urn:li:sponsoredAccount:{self.organization_id}"

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # 1 — Campaign Groups (top-level)
                grp_resp = await client.get(
                    f"{LINKEDIN_API}/adCampaignGroupsV2",
                    headers=self._headers(versioned=True),
                    params={"q": "search", "search.account.values[0]": account_urn},
                )
                grp_resp.raise_for_status()
                groups = {
                    str(g["id"]): g.get("name", "")
                    for g in grp_resp.json().get("elements", [])
                }
                if not groups:
                    return []

                # 2 — Campaigns (mid-level) per group
                campaigns: dict[str, dict[str, str]] = {}
                for gid in groups:
                    cmp_resp = await client.get(
                        f"{LINKEDIN_API}/adCampaignsV2",
                        headers=self._headers(versioned=True),
                        params={
                            "q": "search",
                            "search.campaignGroup.values[0]": f"urn:li:sponsoredCampaignGroup:{gid}",
                        },
                    )
                    cmp_resp.raise_for_status()
                    for c in cmp_resp.json().get("elements", []):
                        campaigns[str(c["id"])] = {
                            "name": c.get("name", ""),
                            "group_id": gid,
                        }

                if not campaigns:
                    return []

                # 3 — Creative-level analytics
                results: list[dict[str, str | float]] = []
                for cid, cinfo in campaigns.items():
                    campaign_urn = f"urn:li:sponsoredCampaign:{cid}"
                    analytics_resp = await client.get(
                        f"{LINKEDIN_API}/adAnalyticsV2",
                        headers=self._headers(versioned=True),
                        params={
                            "q": "analytics",
                            "pivot": "CREATIVE",
                            "dateRange.start.year": str(start_date.year),
                            "dateRange.start.month": str(start_date.month),
                            "dateRange.start.day": str(start_date.day),
                            "dateRange.end.year": str(end_date.year),
                            "dateRange.end.month": str(end_date.month),
                            "dateRange.end.day": str(end_date.day),
                            "timeGranularity": "DAILY",
                            "campaigns[0]": campaign_urn,
                        },
                    )
                    analytics_resp.raise_for_status()

                    for row in analytics_resp.json().get("elements", []):
                        creative_urn = row.get("pivotValue", "")
                        creative_id = (
                            creative_urn.split(":")[-1] if creative_urn else ""
                        )
                        dr = row.get("dateRange", {}).get("start", {})
                        if "year" not in dr:
                            continue
                        metric_date = f"{dr['year']}-{dr.get('month', 1):02d}-{dr.get('day', 1):02d}"

                        results.append(
                            {
                                "campaign_group_id": cinfo["group_id"],
                                "campaign_group_name": groups.get(
                                    cinfo["group_id"], ""
                                ),
                                "campaign_id": cid,
                                "campaign_name": cinfo["name"],
                                "creative_id": creative_id,
                                "creative_name": f"Creative {creative_id}",
                                "date_start": metric_date,
                                "impressions": float(row.get("impressions", 0)),
                                "clicks": float(row.get("clicks", 0)),
                                "spend": float(row.get("costInLocalCurrency", 0)),
                                "conversions": float(
                                    row.get("externalWebsiteConversions", 0)
                                ),
                            }
                        )

        except httpx.HTTPError as e:
            logger.warning("LinkedIn fetch_ads_history failed: %s", e)
            return []

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
