from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from app.adapters.base import ChannelAdapter, MetricData, PostData, PublishResult
from app.config import settings

logger = logging.getLogger(__name__)


class MetaAdsAdapter(ChannelAdapter):
    """Adapter for Meta Ads via the Marketing API."""

    def __init__(
        self,
        access_token: str,
        account_id: str,
        client_id: str | None = None,
        client_secret: str | None = None,
        graph_version: str = "v19.0",
        timeout_seconds: int = 30,
    ) -> None:
        self.access_token = access_token
        self.account_id = account_id.removeprefix("act_")
        self.client_id = client_id or settings.meta_app_id
        self.client_secret = client_secret or settings.meta_app_secret
        self.graph_version = graph_version
        self.timeout_seconds = timeout_seconds

    @property
    def graph_api(self) -> str:
        return f"https://graph.facebook.com/{self.graph_version}"

    @property
    def ads_account_ref(self) -> str:
        return f"act_{self.account_id}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def connect(
        self, auth_code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
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
            return data

    async def refresh_token(self, refresh_token_value: str) -> dict | None:
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
                return data
        except httpx.HTTPError as exc:
            logger.warning("Meta Ads token refresh failed: %s", exc)
            return None

    async def disconnect(self) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=min(self.timeout_seconds, 15)
            ) as client:
                resp = await client.delete(
                    f"{self.graph_api}/me/permissions",
                    headers=self._headers(),
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Meta Ads disconnect failed: %s", exc)

    async def validate_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(
                timeout=min(self.timeout_seconds, 15)
            ) as client:
                resp = await client.get(
                    f"{self.graph_api}/{self.ads_account_ref}",
                    headers=self._headers(),
                    params={"fields": "id,account_id,name"},
                )
                return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("Meta Ads connection validation failed: %s", exc)
            return False

    async def fetch_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        rows = await self.fetch_ads_history(start_date, end_date)
        metrics: list[MetricData] = []
        for row in rows:
            try:
                metric_date = date.fromisoformat(
                    str(row.get("date_start") or start_date.isoformat())
                )
            except ValueError:
                metric_date = start_date
            metrics.extend(
                [
                    MetricData(
                        metric_date=metric_date,
                        metric_type="impressions",
                        value=float(row.get("impressions") or 0),
                    ),
                    MetricData(
                        metric_date=metric_date,
                        metric_type="reach",
                        value=float(row.get("reach") or 0),
                    ),
                    MetricData(
                        metric_date=metric_date,
                        metric_type="clicks",
                        value=float(row.get("clicks") or 0),
                    ),
                    MetricData(
                        metric_date=metric_date,
                        metric_type="spend",
                        value=float(row.get("spend") or 0),
                    ),
                    MetricData(
                        metric_date=metric_date,
                        metric_type="conversions",
                        value=float(row.get("conversions") or 0),
                    ),
                ]
            )
        return metrics

    async def fetch_posts(self, since: datetime | None = None) -> list[PostData]:
        return []

    async def publish_post(
        self,
        content: str,
        *,
        media_urls: list[str] | None = None,
        title: str | None = None,
    ) -> PublishResult:
        raise NotImplementedError("Meta Ads does not support publish_post in this app")

    async def fetch_ads_history(
        self, start_date: date, end_date: date, *, limit: int = 250
    ) -> list[dict[str, str | float]]:
        params = {
            "level": "ad",
            "time_increment": 1,
            "limit": str(limit),
            "fields": ",".join(
                [
                    "campaign_id",
                    "campaign_name",
                    "adset_id",
                    "adset_name",
                    "ad_id",
                    "ad_name",
                    "account_currency",
                    "date_start",
                    "date_stop",
                    "impressions",
                    "reach",
                    "clicks",
                    "spend",
                    "cpc",
                    "ctr",
                    "cpp",
                    "actions",
                ]
            ),
            "time_range": (
                f'{{"since":"{start_date.isoformat()}","until":"{end_date.isoformat()}"}}'
            ),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(
                    f"{self.graph_api}/{self.ads_account_ref}/insights",
                    headers=self._headers(),
                    params=params,
                )
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Meta Ads history fetch failed for %s: %s", self.account_id, exc
            )
            return []

        rows: list[dict[str, str | float]] = []
        for item in payload.get("data", []):
            actions = item.get("actions") or []
            conversions = 0.0
            for action in actions:
                action_type = str(action.get("action_type", ""))
                if action_type in {
                    "purchase",
                    "omni_purchase",
                    "offsite_conversion.fb_pixel_purchase",
                    "lead",
                    "onsite_web_lead",
                }:
                    try:
                        conversions += float(action.get("value") or 0)
                    except (TypeError, ValueError):
                        continue

            rows.append(
                {
                    "campaign_id": str(item.get("campaign_id", "")),
                    "campaign_name": str(item.get("campaign_name", "")),
                    "adset_id": str(item.get("adset_id", "")),
                    "adset_name": str(item.get("adset_name", "")),
                    "ad_id": str(item.get("ad_id", "")),
                    "ad_name": str(item.get("ad_name", "")),
                    "account_currency": str(item.get("account_currency", "")),
                    "date_start": str(item.get("date_start", "")),
                    "date_stop": str(item.get("date_stop", "")),
                    "impressions": float(item.get("impressions") or 0),
                    "reach": float(item.get("reach") or 0),
                    "clicks": float(item.get("clicks") or 0),
                    "spend": float(item.get("spend") or 0),
                    "cpc": float(item.get("cpc") or 0),
                    "ctr": float(item.get("ctr") or 0),
                    "cpp": float(item.get("cpp") or 0),
                    "conversions": conversions,
                }
            )
        return rows
