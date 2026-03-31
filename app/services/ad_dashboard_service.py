"""Query service for the unified ads dashboard — reads from local DB only."""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ad_campaign import (
    Ad,
    AdCampaign,
    AdGroup,
    AdMetric,
    AdPlatform,
)

logger = logging.getLogger(__name__)


class AdDashboardService:
    """Provide aggregated ad performance data from locally synced tables."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_overview(self, *, start_date: date, end_date: date) -> dict[str, float]:
        """Total spend, impressions, clicks, conversions across all platforms."""
        stmt = (
            select(
                func.coalesce(func.sum(AdMetric.spend), 0).label("spend"),
                func.coalesce(func.sum(AdMetric.impressions), 0).label("impressions"),
                func.coalesce(func.sum(AdMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(AdMetric.conversions), 0).label("conversions"),
            )
            .where(AdMetric.metric_date >= start_date)
            .where(AdMetric.metric_date <= end_date)
        )
        row = self.db.execute(stmt).one()
        return {
            "spend": float(row.spend),
            "impressions": float(row.impressions),
            "clicks": float(row.clicks),
            "conversions": float(row.conversions),
        }

    def get_platform_summary(self, *, start_date: date, end_date: date) -> list[dict]:
        """Per-platform totals."""
        stmt = (
            select(
                AdCampaign.platform,
                func.coalesce(func.sum(AdMetric.spend), 0).label("spend"),
                func.coalesce(func.sum(AdMetric.impressions), 0).label("impressions"),
                func.coalesce(func.sum(AdMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(AdMetric.conversions), 0).label("conversions"),
            )
            .join(AdGroup, AdGroup.ad_campaign_id == AdCampaign.id)
            .join(Ad, Ad.ad_group_id == AdGroup.id)
            .join(AdMetric, AdMetric.ad_id == Ad.id)
            .where(AdMetric.metric_date >= start_date)
            .where(AdMetric.metric_date <= end_date)
            .group_by(AdCampaign.platform)
            .order_by(AdCampaign.platform)
        )
        return [
            {
                "platform": row.platform.value,
                "spend": float(row.spend),
                "impressions": float(row.impressions),
                "clicks": float(row.clicks),
                "conversions": float(row.conversions),
            }
            for row in self.db.execute(stmt).all()
        ]

    def get_campaigns(
        self,
        *,
        platform: AdPlatform | None = None,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """List ad campaigns with aggregated metrics."""
        stmt = (
            select(
                AdCampaign.id,
                AdCampaign.platform,
                AdCampaign.external_id,
                AdCampaign.name,
                AdCampaign.status,
                AdCampaign.campaign_id,
                func.coalesce(func.sum(AdMetric.spend), 0).label("spend"),
                func.coalesce(func.sum(AdMetric.impressions), 0).label("impressions"),
                func.coalesce(func.sum(AdMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(AdMetric.conversions), 0).label("conversions"),
            )
            .join(AdGroup, AdGroup.ad_campaign_id == AdCampaign.id)
            .join(Ad, Ad.ad_group_id == AdGroup.id)
            .join(AdMetric, AdMetric.ad_id == Ad.id)
            .where(AdMetric.metric_date >= start_date)
            .where(AdMetric.metric_date <= end_date)
            .group_by(AdCampaign.id)
            .order_by(func.sum(AdMetric.spend).desc())
        )
        if platform is not None:
            stmt = stmt.where(AdCampaign.platform == platform)

        return [
            {
                "id": str(row.id),
                "platform": row.platform.value,
                "external_id": row.external_id,
                "name": row.name,
                "status": row.status.value,
                "campaign_id": str(row.campaign_id) if row.campaign_id else None,
                "spend": float(row.spend),
                "impressions": float(row.impressions),
                "clicks": float(row.clicks),
                "conversions": float(row.conversions),
            }
            for row in self.db.execute(stmt).all()
        ]

    def get_campaign_detail(
        self,
        ad_campaign_id: UUID,
        *,
        start_date: date,
        end_date: date,
    ) -> dict | None:
        """Drill into a single ad campaign with ad group and ad breakdowns."""
        ac = self.db.get(AdCampaign, ad_campaign_id)
        if ac is None:
            return None

        # Ad group level aggregations
        group_stmt = (
            select(
                AdGroup.id,
                AdGroup.external_id,
                AdGroup.name,
                AdGroup.status,
                func.coalesce(func.sum(AdMetric.spend), 0).label("spend"),
                func.coalesce(func.sum(AdMetric.impressions), 0).label("impressions"),
                func.coalesce(func.sum(AdMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(AdMetric.conversions), 0).label("conversions"),
            )
            .join(Ad, Ad.ad_group_id == AdGroup.id)
            .join(AdMetric, AdMetric.ad_id == Ad.id)
            .where(AdGroup.ad_campaign_id == ad_campaign_id)
            .where(AdMetric.metric_date >= start_date)
            .where(AdMetric.metric_date <= end_date)
            .group_by(AdGroup.id)
            .order_by(func.sum(AdMetric.spend).desc())
        )
        ad_groups = [
            {
                "id": str(row.id),
                "external_id": row.external_id,
                "name": row.name,
                "status": row.status.value,
                "spend": float(row.spend),
                "impressions": float(row.impressions),
                "clicks": float(row.clicks),
                "conversions": float(row.conversions),
            }
            for row in self.db.execute(group_stmt).all()
        ]

        # Ad level aggregations
        ad_stmt = (
            select(
                Ad.id,
                Ad.external_id,
                Ad.name,
                Ad.status,
                AdGroup.name.label("group_name"),
                func.coalesce(func.sum(AdMetric.spend), 0).label("spend"),
                func.coalesce(func.sum(AdMetric.impressions), 0).label("impressions"),
                func.coalesce(func.sum(AdMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(AdMetric.conversions), 0).label("conversions"),
            )
            .join(AdGroup, Ad.ad_group_id == AdGroup.id)
            .join(AdMetric, AdMetric.ad_id == Ad.id)
            .where(AdGroup.ad_campaign_id == ad_campaign_id)
            .where(AdMetric.metric_date >= start_date)
            .where(AdMetric.metric_date <= end_date)
            .group_by(Ad.id, AdGroup.name)
            .order_by(func.sum(AdMetric.spend).desc())
        )
        ads = [
            {
                "id": str(row.id),
                "external_id": row.external_id,
                "name": row.name,
                "status": row.status.value,
                "group_name": row.group_name,
                "spend": float(row.spend),
                "impressions": float(row.impressions),
                "clicks": float(row.clicks),
                "conversions": float(row.conversions),
            }
            for row in self.db.execute(ad_stmt).all()
        ]

        return {
            "campaign": {
                "id": str(ac.id),
                "platform": ac.platform.value,
                "external_id": ac.external_id,
                "name": ac.name,
                "status": ac.status.value,
                "campaign_id": str(ac.campaign_id) if ac.campaign_id else None,
            },
            "ad_groups": ad_groups,
            "ads": ads,
        }

    def get_daily_totals(
        self,
        *,
        platform: AdPlatform | None = None,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """Time-series aggregation by date."""
        stmt = (
            select(
                AdMetric.metric_date,
                func.coalesce(func.sum(AdMetric.spend), 0).label("spend"),
                func.coalesce(func.sum(AdMetric.impressions), 0).label("impressions"),
                func.coalesce(func.sum(AdMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(AdMetric.conversions), 0).label("conversions"),
            )
            .where(AdMetric.metric_date >= start_date)
            .where(AdMetric.metric_date <= end_date)
            .group_by(AdMetric.metric_date)
            .order_by(AdMetric.metric_date)
        )
        if platform is not None:
            stmt = (
                stmt.join(Ad, AdMetric.ad_id == Ad.id)
                .join(AdGroup, Ad.ad_group_id == AdGroup.id)
                .join(AdCampaign, AdGroup.ad_campaign_id == AdCampaign.id)
                .where(AdCampaign.platform == platform)
            )

        return [
            {
                "date": str(row.metric_date),
                "spend": float(row.spend),
                "impressions": float(row.impressions),
                "clicks": float(row.clicks),
                "conversions": float(row.conversions),
            }
            for row in self.db.execute(stmt).all()
        ]

    def link_to_campaign(self, ad_campaign_id: UUID, campaign_id: UUID | None) -> None:
        """Associate or disassociate an ad campaign with an internal Campaign."""
        ac = self.db.get(AdCampaign, ad_campaign_id)
        if ac is None:
            raise ValueError(f"AdCampaign {ad_campaign_id} not found")
        ac.campaign_id = campaign_id
        self.db.flush()
        logger.info("Linked AdCampaign %s to Campaign %s", ad_campaign_id, campaign_id)
