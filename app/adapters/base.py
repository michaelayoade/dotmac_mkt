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


class ChannelAdapter(ABC):
    """Base interface for all channel integrations."""

    @abstractmethod
    async def connect(self, auth_code: str) -> dict:
        """Complete OAuth flow, return token dict."""

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
    async def fetch_posts(
        self, since: datetime | None = None
    ) -> list[PostData]:
        """Sync published content back."""
