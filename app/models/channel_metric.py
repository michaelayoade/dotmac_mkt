from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Index, Numeric, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class MetricType(str, enum.Enum):
    impressions = "impressions"
    reach = "reach"
    clicks = "clicks"
    engagement = "engagement"
    spend = "spend"
    conversions = "conversions"


class ChannelMetric(TimestampMixin, Base):
    __tablename__ = "channel_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE")
    )
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=True
    )
    metric_date: Mapped[date] = mapped_column(Date)
    metric_type: Mapped[MetricType] = mapped_column(Enum(MetricType))
    value: Mapped[float] = mapped_column(Numeric(18, 6))

    channel = relationship("Channel", back_populates="metrics")

    __table_args__ = (
        Index(
            "ix_channel_metric_post",
            "channel_id",
            "post_id",
            "metric_date",
            "metric_type",
            unique=True,
            postgresql_where=text("post_id IS NOT NULL"),
        ),
        Index(
            "ix_channel_metric_channel",
            "channel_id",
            "metric_date",
            "metric_type",
            unique=True,
            postgresql_where=text("post_id IS NULL"),
        ),
    )
