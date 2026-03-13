from __future__ import annotations

import contextlib
import logging
from datetime import date, datetime

import httpx

from app.adapters.base import ChannelAdapter, MetricData, PostData
from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v19.0"


class MetaAdapter(ChannelAdapter):
    """Adapter for Instagram and Facebook via Meta Graph API v19."""

    def __init__(self, access_token: str, account_id: str) -> None:
        self.access_token = access_token
        self.account_id = account_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def connect(self, auth_code: str) -> dict:
        """Exchange auth code for a long-lived access token."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GRAPH_API}/oauth/access_token",
                params={
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "code": auth_code,
                    "redirect_uri": "",  # must match app config
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("access_token", self.access_token)
            logger.info("Meta OAuth token exchanged for account %s", self.account_id)
            return data

    async def disconnect(self) -> None:
        """Revoke permissions (best-effort)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.delete(
                    f"{GRAPH_API}/me/permissions",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                logger.info("Meta permissions revoked for account %s", self.account_id)
        except httpx.HTTPError as e:
            logger.warning("Meta disconnect failed: %s", e)

    async def validate_connection(self) -> bool:
        """Check whether the access token is still valid."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{GRAPH_API}/me",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Meta connection validation failed: %s", e)
            return False

    async def fetch_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        """Fetch insights (impressions, reach, engagement) for the account."""
        metrics_param = "impressions,reach,engagement"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{GRAPH_API}/{self.account_id}/insights",
                    headers=self._headers(),
                    params={
                        "metric": metrics_param,
                        "period": "day",
                        "since": start_date.isoformat(),
                        "until": end_date.isoformat(),
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning("Meta fetch_analytics failed: %s", e)
            return []

        results: list[MetricData] = []
        for metric_block in data.get("data", []):
            metric_name = metric_block.get("name", "")
            for value_entry in metric_block.get("values", []):
                try:
                    results.append(
                        MetricData(
                            metric_date=date.fromisoformat(
                                value_entry["end_time"][:10]
                            ),
                            metric_type=metric_name,
                            value=float(value_entry.get("value", 0)),
                        )
                    )
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning("Skipping malformed metric entry: %s", e)
        return results

    async def fetch_posts(
        self, since: datetime | None = None
    ) -> list[PostData]:
        """Fetch media/feed posts from the account."""
        params: dict[str, str] = {"fields": "id,message,created_time"}
        if since:
            params["since"] = str(int(since.timestamp()))

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Try /media first (Instagram), fall back to /feed (Facebook)
                resp = await client.get(
                    f"{GRAPH_API}/{self.account_id}/media",
                    headers=self._headers(),
                    params=params,
                )
                if resp.status_code != 200:
                    resp = await client.get(
                        f"{GRAPH_API}/{self.account_id}/feed",
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
