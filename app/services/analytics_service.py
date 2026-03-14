import logging
import uuid
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.channel_metric import ChannelMetric, MetricType
from app.models.post import Post

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for marketing analytics and channel metrics."""

    def __init__(self, db: Session):
        self.db = db

    def get_channel_metrics(
        self,
        channel_id: UUID,
        *,
        start_date: date,
        end_date: date,
    ) -> list[ChannelMetric]:
        stmt = (
            select(ChannelMetric)
            .where(ChannelMetric.channel_id == channel_id)
            .where(ChannelMetric.metric_date >= start_date)
            .where(ChannelMetric.metric_date <= end_date)
            .order_by(ChannelMetric.metric_date)
        )
        return list(self.db.scalars(stmt).all())

    def get_campaign_metrics(
        self,
        campaign_id: UUID,
        *,
        start_date: date,
        end_date: date,
    ) -> list[ChannelMetric]:
        stmt = (
            select(ChannelMetric)
            .join(Post, ChannelMetric.post_id == Post.id)
            .where(Post.campaign_id == campaign_id)
            .where(ChannelMetric.metric_date >= start_date)
            .where(ChannelMetric.metric_date <= end_date)
            .order_by(ChannelMetric.metric_date)
        )
        return list(self.db.scalars(stmt).all())

    def get_overview(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> dict:
        stmt = (
            select(
                ChannelMetric.metric_type,
                func.sum(ChannelMetric.value).label("total"),
            )
            .where(ChannelMetric.metric_date >= start_date)
            .where(ChannelMetric.metric_date <= end_date)
            .group_by(ChannelMetric.metric_type)
        )
        rows = self.db.execute(stmt).all()
        return {row.metric_type.value: float(row.total) for row in rows}

    def get_daily_totals(
        self,
        *,
        start_date: date,
        end_date: date,
        channel_id: UUID | None = None,
    ) -> list[dict]:
        """Return daily-aggregated metrics as a list of dicts sorted by date."""
        stmt = (
            select(
                ChannelMetric.metric_date,
                ChannelMetric.metric_type,
                func.sum(ChannelMetric.value).label("total"),
            )
            .where(ChannelMetric.metric_date >= start_date)
            .where(ChannelMetric.metric_date <= end_date)
            .where(ChannelMetric.metric_type.in_([
                MetricType.impressions,
                MetricType.reach,
                MetricType.clicks,
                MetricType.engagement,
            ]))
        )
        if channel_id is not None:
            stmt = stmt.where(ChannelMetric.channel_id == channel_id)
        stmt = stmt.group_by(ChannelMetric.metric_date, ChannelMetric.metric_type)
        stmt = stmt.order_by(ChannelMetric.metric_date)

        rows = self.db.execute(stmt).all()

        by_date: dict[date, dict[str, int]] = {}
        for row in rows:
            d = row.metric_date
            if d not in by_date:
                by_date[d] = {"impressions": 0, "reach": 0, "clicks": 0, "engagement": 0}
            by_date[d][row.metric_type.value] = int(row.total)

        return [
            {"date": d.isoformat(), **metrics}
            for d, metrics in sorted(by_date.items())
        ]

    def upsert_metric(
        self,
        channel_id: UUID,
        metric_date: date,
        metric_type: MetricType,
        value: float,
        post_id: UUID | None = None,
    ) -> ChannelMetric:
        # Query for existing metric matching the natural key
        stmt = select(ChannelMetric).where(
            ChannelMetric.channel_id == channel_id,
            ChannelMetric.metric_date == metric_date,
            ChannelMetric.metric_type == metric_type,
        )
        if post_id is not None:
            stmt = stmt.where(ChannelMetric.post_id == post_id)
        else:
            stmt = stmt.where(ChannelMetric.post_id.is_(None))

        existing = self.db.scalar(stmt)

        if existing is not None:
            existing.value = value
            self.db.flush()
            logger.info("Updated metric %s for channel %s", metric_type.value, channel_id)
            return existing

        record = ChannelMetric(
            id=uuid.uuid4(),
            channel_id=channel_id,
            post_id=post_id,
            metric_date=metric_date,
            metric_type=metric_type,
            value=value,
        )
        self.db.add(record)
        self.db.flush()
        logger.info("Created metric %s for channel %s", metric_type.value, channel_id)
        return record
