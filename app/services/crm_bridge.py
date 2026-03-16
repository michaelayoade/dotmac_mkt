import logging
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)


class CrmBridge:
    """Bridge service for communicating with the DotMac CRM API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def is_configured(self) -> bool:
        return bool(self.base_url) and bool(self.api_key)

    async def fetch_segments(self) -> list[dict]:
        if not self.is_configured():
            raise RuntimeError("CRM bridge is not configured")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/segments",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError:
            logger.error("Failed to connect to CRM at %s", self.base_url)
            return []
        except httpx.HTTPStatusError as exc:
            logger.error(
                "CRM returned %s for segments request", exc.response.status_code
            )
            return []
        except httpx.TimeoutException:
            logger.error("CRM request timed out for segments")
            return []

    async def link_campaign(self, campaign_id: UUID, crm_campaign_id: str) -> dict:
        if not self.is_configured():
            raise RuntimeError("CRM bridge is not configured")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/campaigns/{crm_campaign_id}/link",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"marketing_campaign_id": str(campaign_id)},
                )
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError:
            logger.error("Failed to connect to CRM at %s", self.base_url)
            raise RuntimeError("CRM connection failed")
        except httpx.HTTPStatusError as exc:
            logger.error(
                "CRM returned %s for link_campaign request",
                exc.response.status_code,
            )
            raise RuntimeError(f"CRM returned status {exc.response.status_code}")
        except httpx.TimeoutException:
            logger.error("CRM request timed out for link_campaign")
            raise RuntimeError("CRM request timed out")
