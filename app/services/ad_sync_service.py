"""Upsert ad hierarchy and metrics from adapter flat rows."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ad_campaign import (
    Ad,
    AdCampaign,
    AdEntityStatus,
    AdGroup,
    AdMetric,
    AdPlatform,
)

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _safe_decimal(value: object) -> Decimal:
    """Convert a value to Decimal, falling back to zero on bad input."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO


# Maps platform field names from adapter flat dicts to normalised hierarchy keys.
PLATFORM_FIELD_MAP: dict[AdPlatform, dict[str, str]] = {
    AdPlatform.meta: {
        "campaign_id": "campaign_id",
        "campaign_name": "campaign_name",
        "group_id": "adset_id",
        "group_name": "adset_name",
        "ad_id": "ad_id",
        "ad_name": "ad_name",
    },
    AdPlatform.google: {
        "campaign_id": "campaign_id",
        "campaign_name": "campaign_name",
        "group_id": "ad_group_id",
        "group_name": "ad_group_name",
        "ad_id": "ad_id",
        "ad_name": "ad_name",
    },
    AdPlatform.linkedin: {
        "campaign_id": "campaign_group_id",
        "campaign_name": "campaign_group_name",
        "group_id": "campaign_id",
        "group_name": "campaign_name",
        "ad_id": "creative_id",
        "ad_name": "creative_name",
    },
}


class AdSyncService:
    """Upsert ad hierarchy and daily metrics from adapter flat rows."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_platform_rows(
        self,
        channel_id: UUID,
        platform: AdPlatform,
        rows: list[dict],
    ) -> int:
        """Process flat dicts from adapter, upsert hierarchy + metrics.

        Returns count of metric rows upserted.
        """
        field_map = PLATFORM_FIELD_MAP[platform]

        # In-memory caches to reduce SELECTs
        campaign_cache: dict[str, AdCampaign] = {}
        group_cache: dict[tuple[UUID, str], AdGroup] = {}
        ad_cache: dict[tuple[UUID, str], Ad] = {}
        metrics_upserted = 0

        # Pre-load existing campaigns for this channel+platform
        stmt = select(AdCampaign).where(
            AdCampaign.channel_id == channel_id,
            AdCampaign.platform == platform,
        )
        for ac in self.db.scalars(stmt).all():
            campaign_cache[ac.external_id] = ac

        for row in rows:
            ext_campaign_id = str(row.get(field_map["campaign_id"], ""))
            ext_campaign_name = str(row.get(field_map["campaign_name"], ""))
            ext_group_id = str(row.get(field_map["group_id"], ""))
            ext_group_name = str(row.get(field_map["group_name"], ""))
            ext_ad_id = str(row.get(field_map["ad_id"], ""))
            ext_ad_name = str(row.get(field_map["ad_name"], ""))

            if not ext_campaign_id or not ext_ad_id:
                continue

            # Upsert AdCampaign
            ac = campaign_cache.get(ext_campaign_id)
            if ac is None:
                ac = AdCampaign(
                    channel_id=channel_id,
                    platform=platform,
                    external_id=ext_campaign_id,
                    name=ext_campaign_name,
                    status=AdEntityStatus.active,
                )
                self.db.add(ac)
                self.db.flush()
                campaign_cache[ext_campaign_id] = ac
            elif ac.name != ext_campaign_name:
                ac.name = ext_campaign_name

            # Upsert AdGroup
            group_key = (ac.id, ext_group_id)
            ag = group_cache.get(group_key)
            if ag is None:
                ag = self.db.scalar(
                    select(AdGroup).where(
                        AdGroup.ad_campaign_id == ac.id,
                        AdGroup.external_id == ext_group_id,
                    )
                )
            if ag is None:
                ag = AdGroup(
                    ad_campaign_id=ac.id,
                    external_id=ext_group_id,
                    name=ext_group_name,
                    status=AdEntityStatus.active,
                )
                self.db.add(ag)
                self.db.flush()
            elif ag.name != ext_group_name:
                ag.name = ext_group_name
            group_cache[group_key] = ag

            # Upsert Ad
            ad_key = (ag.id, ext_ad_id)
            ad = ad_cache.get(ad_key)
            if ad is None:
                ad = self.db.scalar(
                    select(Ad).where(
                        Ad.ad_group_id == ag.id,
                        Ad.external_id == ext_ad_id,
                    )
                )
            if ad is None:
                ad = Ad(
                    ad_group_id=ag.id,
                    external_id=ext_ad_id,
                    name=ext_ad_name,
                    status=AdEntityStatus.active,
                )
                self.db.add(ad)
                self.db.flush()
            elif ad.name != ext_ad_name:
                ad.name = ext_ad_name
            ad_cache[ad_key] = ad

            # Upsert AdMetric
            date_str = str(row.get("date_start", row.get("date", "")))
            if not date_str:
                continue
            metric_date = date.fromisoformat(date_str)

            metric = self.db.scalar(
                select(AdMetric).where(
                    AdMetric.ad_id == ad.id,
                    AdMetric.metric_date == metric_date,
                )
            )
            if metric is None:
                metric = AdMetric(ad_id=ad.id, metric_date=metric_date)
                self.db.add(metric)

            metric.impressions = _safe_decimal(row.get("impressions", 0))
            metric.reach = _safe_decimal(row.get("reach", 0))
            metric.clicks = _safe_decimal(row.get("clicks", 0))
            metric.spend = _safe_decimal(row.get("spend", 0))
            metric.conversions = _safe_decimal(row.get("conversions", 0))
            metric.ctr = _safe_decimal(row.get("ctr", 0))
            metric.cpc = _safe_decimal(row.get("cpc", row.get("average_cpc", 0)))
            metric.currency_code = str(row.get("currency_code", "")) or None

            metrics_upserted += 1

        self.db.flush()
        return metrics_upserted
