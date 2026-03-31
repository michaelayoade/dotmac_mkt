from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

logger = logging.getLogger(__name__)


@dataclass
class MetricData:
    metric_date: date
    metric_type: str  # maps to MetricType enum value
    value: float
    post_id: str | None = None  # external post ID


@dataclass
class PostData:
    external_id: str
    title: str
    content: str
    published_at: datetime | None = None


@dataclass
class PublishResult:
    external_post_id: str
    url: str | None = None


@dataclass
class UpdateResult:
    external_post_id: str | None = None
    url: str | None = None


class ChannelAdapter(ABC):
    """Base interface for all channel integrations."""

    supports_remote_update = False
    supports_remote_delete = False

    @abstractmethod
    async def connect(
        self, auth_code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
        """Complete OAuth flow, return token dict."""

    async def refresh_token(self, refresh_token_value: str) -> dict | None:
        """Refresh an expired access token. Returns new token dict or None."""
        return None

    @abstractmethod
    async def disconnect(self) -> None:
        """Revoke tokens (best-effort)."""

    @abstractmethod
    async def validate_connection(self) -> bool:
        """Health check — are tokens valid?"""

    @abstractmethod
    async def fetch_analytics(
        self, start_date: date, end_date: date
    ) -> list[MetricData]:
        """Pull metrics for a date range."""

    @abstractmethod
    async def fetch_posts(self, since: datetime | None = None) -> list[PostData]:
        """Sync published content back."""

    @abstractmethod
    async def publish_post(
        self,
        content: str,
        *,
        media_urls: list[str] | None = None,
        title: str | None = None,
    ) -> PublishResult:
        """Publish a post to this channel. Returns the external post ID and URL."""

    async def update_post(
        self,
        external_post_id: str,
        content: str,
        *,
        media_urls: list[str] | None = None,
        title: str | None = None,
    ) -> UpdateResult:
        """Update a previously published post on this channel."""
        raise NotImplementedError("Remote post updates are not supported")

    async def delete_post(self, external_post_id: str) -> None:
        """Delete a previously published post on this channel."""
        raise NotImplementedError("Remote post deletion is not supported")
