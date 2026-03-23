import logging
import uuid
from datetime import date
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.channel_metric import ChannelMetric, MetricType
from app.models.post import Post

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for marketing analytics and channel metrics."""

    def __init__(self, db: Session):
        self.db = db

    def _apply_metric_filters(
        self,
        stmt: Select,
        *,
        start_date: date,
        end_date: date,
        channel_id: UUID | None = None,
        post_id: UUID | None = None,
        metric_date: date | None = None,
    ) -> Select:
        stmt = stmt.where(ChannelMetric.metric_date >= start_date).where(
            ChannelMetric.metric_date <= end_date
        )
        if channel_id is not None:
            stmt = stmt.where(ChannelMetric.channel_id == channel_id)
        if post_id is not None:
            stmt = stmt.where(ChannelMetric.post_id == post_id)
        if metric_date is not None:
            stmt = stmt.where(ChannelMetric.metric_date == metric_date)
        return stmt

    def get_channel_metrics(
        self,
        channel_id: UUID,
        *,
        start_date: date,
        end_date: date,
        post_id: UUID | None = None,
        metric_date: date | None = None,
    ) -> list[ChannelMetric]:
        stmt = self._apply_metric_filters(
            select(ChannelMetric).where(ChannelMetric.channel_id == channel_id),
            start_date=start_date,
            end_date=end_date,
            post_id=post_id,
            metric_date=metric_date,
        )
        stmt = stmt.order_by(ChannelMetric.metric_date)
        return list(self.db.scalars(stmt).all())

    def get_campaign_metrics(
        self,
        campaign_id: UUID,
        *,
        start_date: date,
        end_date: date,
        post_id: UUID | None = None,
        metric_date: date | None = None,
    ) -> list[ChannelMetric]:
        stmt = self._apply_metric_filters(
            select(ChannelMetric)
            .join(Post, ChannelMetric.post_id == Post.id)
            .where(Post.campaign_id == campaign_id)
            .order_by(ChannelMetric.metric_date),
            start_date=start_date,
            end_date=end_date,
            post_id=post_id,
            metric_date=metric_date,
        )
        return list(self.db.scalars(stmt).all())

    def get_overview(
        self,
        *,
        start_date: date,
        end_date: date,
        post_id: UUID | None = None,
        metric_date: date | None = None,
    ) -> dict:
        stmt = self._apply_metric_filters(
            select(
                ChannelMetric.metric_type,
                func.sum(ChannelMetric.value).label("total"),
            ),
            start_date=start_date,
            end_date=end_date,
            post_id=post_id,
            metric_date=metric_date,
        )
        stmt = stmt.group_by(ChannelMetric.metric_type)
        rows = self.db.execute(stmt).all()
        return {row.metric_type.value: float(row.total) for row in rows}

    def get_daily_totals(
        self,
        *,
        start_date: date,
        end_date: date,
        channel_id: UUID | None = None,
        post_id: UUID | None = None,
        metric_date: date | None = None,
    ) -> list[dict]:
        """Return daily-aggregated metrics as a list of dicts sorted by date."""
        stmt = self._apply_metric_filters(
            select(
                ChannelMetric.metric_date,
                ChannelMetric.metric_type,
                func.sum(ChannelMetric.value).label("total"),
            ).where(
                ChannelMetric.metric_type.in_(
                    [
                        MetricType.impressions,
                        MetricType.reach,
                        MetricType.clicks,
                        MetricType.engagement,
                    ]
                )
            ),
            start_date=start_date,
            end_date=end_date,
            channel_id=channel_id,
            post_id=post_id,
            metric_date=metric_date,
        )
        stmt = stmt.group_by(ChannelMetric.metric_date, ChannelMetric.metric_type)
        stmt = stmt.order_by(ChannelMetric.metric_date)

        rows = self.db.execute(stmt).all()

        by_date: dict[date, dict[str, int]] = {}
        for row in rows:
            d = row.metric_date
            if d not in by_date:
                by_date[d] = {
                    "impressions": 0,
                    "reach": 0,
                    "clicks": 0,
                    "engagement": 0,
                }
            by_date[d][row.metric_type.value] = int(row.total)

        return [
            {"date": d.isoformat(), **metrics} for d, metrics in sorted(by_date.items())
        ]

    def get_daily_metric_breakdown(
        self,
        *,
        start_date: date,
        end_date: date,
        channel_id: UUID | None = None,
        post_id: UUID | None = None,
        metric_date: date | None = None,
    ) -> list[dict[str, str | float]]:
        """Return daily totals for every metric type in the selected range."""
        stmt = self._apply_metric_filters(
            select(
                ChannelMetric.metric_date,
                ChannelMetric.metric_type,
                func.sum(ChannelMetric.value).label("total"),
            ),
            start_date=start_date,
            end_date=end_date,
            channel_id=channel_id,
            post_id=post_id,
            metric_date=metric_date,
        )
        stmt = stmt.group_by(ChannelMetric.metric_date, ChannelMetric.metric_type)
        stmt = stmt.order_by(ChannelMetric.metric_date, ChannelMetric.metric_type)

        rows = self.db.execute(stmt).all()
        return [
            {
                "date": row.metric_date.isoformat(),
                "metric_type": row.metric_type.value,
                "total": float(row.total),
            }
            for row in rows
        ]

    def get_post_filter_options(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, str]]:
        stmt = (
            select(Post.id, Post.title, Channel.name)
            .join(ChannelMetric, ChannelMetric.post_id == Post.id)
            .outerjoin(Channel, Post.channel_id == Channel.id)
        )
        stmt = self._apply_metric_filters(
            stmt,
            start_date=start_date,
            end_date=end_date,
        )
        stmt = stmt.group_by(Post.id, Post.title, Channel.name).order_by(
            func.max(ChannelMetric.metric_date).desc(), Post.title.asc()
        )
        rows = self.db.execute(stmt).all()
        return [
            {
                "id": str(row.id),
                "title": row.title,
                "channel_name": row.name or "Unknown channel",
            }
            for row in rows
        ]

    def get_post_impression_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        post_id: UUID | None = None,
        metric_date: date | None = None,
    ) -> list[dict[str, str | int]]:
        stmt = (
            select(
                ChannelMetric.metric_date,
                Post.id,
                Post.title,
                Channel.name.label("channel_name"),
                func.sum(ChannelMetric.value).label("impressions"),
            )
            .join(Post, ChannelMetric.post_id == Post.id)
            .outerjoin(Channel, Post.channel_id == Channel.id)
            .where(ChannelMetric.metric_type == MetricType.impressions)
        )
        stmt = self._apply_metric_filters(
            stmt,
            start_date=start_date,
            end_date=end_date,
            post_id=post_id,
            metric_date=metric_date,
        )
        stmt = stmt.group_by(
            ChannelMetric.metric_date, Post.id, Post.title, Channel.name
        ).order_by(
            ChannelMetric.metric_date.desc(),
            func.sum(ChannelMetric.value).desc(),
        )
        rows = self.db.execute(stmt).all()
        return [
            {
                "date": row.metric_date.isoformat(),
                "post_id": str(row.id),
                "post_title": row.title,
                "channel_name": row.channel_name or "Unknown channel",
                "impressions": int(row.impressions),
            }
            for row in rows
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
            logger.info(
                "Updated metric %s for channel %s", metric_type.value, channel_id
            )
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
