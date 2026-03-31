"""Dashboard aggregation — stats, channel health, sparkline, campaign distribution."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, DriveStatus
from app.models.campaign import Campaign, CampaignStatus
from app.models.channel import Channel, ChannelStatus
from app.models.post import Post
from app.models.task import Task, TaskStatus
from app.services.analytics_service import AnalyticsService
from app.services.campaign_service import CampaignService
from app.services.post_service import PostService

logger = logging.getLogger(__name__)


@dataclass
class QuickStats:
    total_campaigns: int
    total_assets: int
    active_tasks: int
    connected_channels: int


@dataclass
class ChannelHealth:
    name: str
    status: str  # "healthy" | "error" | "disconnected"


@dataclass
class DashboardData:
    active_campaigns: list[Campaign] = field(default_factory=list)
    upcoming_posts: list[Post] = field(default_factory=list)
    channels: list[Channel] = field(default_factory=list)
    quick_stats: QuickStats = field(default_factory=lambda: QuickStats(0, 0, 0, 0))
    channel_health: list[ChannelHealth] = field(default_factory=list)
    sparkline_data: list[dict] = field(default_factory=list)
    impressions_change: float = 0.0
    campaign_status_counts: dict[str, int] = field(default_factory=dict)


class DashboardService:
    """Aggregates data for the marketing dashboard."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_quick_stats(self, *, person_id: UUID) -> QuickStats:
        """Campaign count, asset count, active tasks for person, connected channels."""
        campaign_svc = CampaignService(self.db)
        total_campaigns = campaign_svc.count()

        total_assets = (
            self.db.scalar(
                select(func.count(Asset.id)).where(
                    Asset.drive_status != DriveStatus.missing
                )
            )
            or 0
        )

        active_tasks = (
            self.db.scalar(
                select(func.count(Task.id)).where(
                    Task.status.in_([TaskStatus.todo, TaskStatus.in_progress]),
                    Task.assignee_id == person_id,
                )
            )
            or 0
        )

        connected_channels = (
            self.db.scalar(
                select(func.count(Channel.id)).where(
                    Channel.status == ChannelStatus.connected
                )
            )
            or 0
        )

        return QuickStats(
            total_campaigns=total_campaigns,
            total_assets=total_assets,
            active_tasks=active_tasks,
            connected_channels=connected_channels,
        )

    def get_channel_health(self) -> list[ChannelHealth]:
        """Map channel status to healthy/error/disconnected labels."""
        channels = list(self.db.scalars(select(Channel).order_by(Channel.name)).all())
        health = []
        for ch in channels:
            if ch.status == ChannelStatus.connected:
                label = "healthy"
            elif ch.status == ChannelStatus.error:
                label = "error"
            else:
                label = "disconnected"
            health.append(ChannelHealth(name=ch.name, status=label))
        return health

    def get_sparkline_data(self, *, days: int = 7) -> tuple[list[dict], float]:
        """Daily impressions for last N days and percent change vs prior period.

        Returns (sparkline_data, impressions_change_pct).
        """
        today_date = date.today()
        analytics_svc = AnalyticsService(self.db)

        sparkline_data = analytics_svc.get_daily_totals(
            start_date=today_date - timedelta(days=days - 1),
            end_date=today_date,
        )

        prior_data = analytics_svc.get_daily_totals(
            start_date=today_date - timedelta(days=(days * 2) - 1),
            end_date=today_date - timedelta(days=days),
        )

        current_impressions = sum(d["impressions"] for d in sparkline_data)
        prior_impressions = sum(d["impressions"] for d in prior_data)

        impressions_change = (
            round(
                (current_impressions - prior_impressions) / prior_impressions * 100,
                1,
            )
            if prior_impressions > 0
            else 0.0
        )
        return sparkline_data, impressions_change

    def get_campaign_status_distribution(self) -> dict[str, int]:
        """Count campaigns per status for the donut chart."""
        campaign_svc = CampaignService(self.db)
        return {
            status.value: campaign_svc.count(status=status) for status in CampaignStatus
        }

    def get_dashboard_data(self, *, person_id: UUID) -> DashboardData:
        """Assemble all dashboard widgets in a single call."""
        campaign_svc = CampaignService(self.db)
        post_svc = PostService(self.db)

        active_campaigns = campaign_svc.list_all(status=CampaignStatus.active, limit=5)
        upcoming_posts = post_svc.list_scheduled(days_ahead=7)[:10]
        channels = list(self.db.scalars(select(Channel).order_by(Channel.name)).all())

        quick_stats = self.get_quick_stats(person_id=person_id)
        channel_health = self.get_channel_health()
        sparkline_data, impressions_change = self.get_sparkline_data()
        campaign_status_counts = self.get_campaign_status_distribution()

        return DashboardData(
            active_campaigns=active_campaigns,
            upcoming_posts=upcoming_posts,
            channels=channels,
            quick_stats=quick_stats,
            channel_health=channel_health,
            sparkline_data=sparkline_data,
            impressions_change=impressions_change,
            campaign_status_counts=campaign_status_counts,
        )
