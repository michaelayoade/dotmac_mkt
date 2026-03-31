"""Ad campaign hierarchy models for tracking externally-created ads."""

from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class AdPlatform(str, enum.Enum):
    meta = "meta"
    google = "google"
    linkedin = "linkedin"


class AdEntityStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    removed = "removed"
    unknown = "unknown"


class AdCampaign(TimestampMixin, Base):
    """Top-level ad campaign synced from an ad platform."""

    __tablename__ = "ad_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE")
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform: Mapped[AdPlatform] = mapped_column(Enum(AdPlatform))
    external_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(500))
    status: Mapped[AdEntityStatus] = mapped_column(
        Enum(AdEntityStatus), default=AdEntityStatus.unknown
    )

    channel = relationship("Channel")
    campaign = relationship("Campaign", back_populates="ad_campaigns")
    ad_groups: Mapped[list[AdGroup]] = relationship(
        back_populates="ad_campaign", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "platform",
            "external_id",
            name="uq_ad_campaign_channel_platform_ext",
        ),
        Index("ix_ad_campaign_channel_id", "channel_id"),
        Index("ix_ad_campaign_campaign_id", "campaign_id"),
    )


class AdGroup(TimestampMixin, Base):
    """Mid-level grouping: Meta Ad Set / Google Ad Group / LinkedIn Campaign."""

    __tablename__ = "ad_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ad_campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ad_campaigns.id", ondelete="CASCADE")
    )
    external_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(500))
    status: Mapped[AdEntityStatus] = mapped_column(
        Enum(AdEntityStatus), default=AdEntityStatus.unknown
    )

    ad_campaign: Mapped[AdCampaign] = relationship(back_populates="ad_groups")
    ads: Mapped[list[Ad]] = relationship(
        back_populates="ad_group", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "ad_campaign_id", "external_id", name="uq_ad_group_campaign_ext"
        ),
        Index("ix_ad_group_ad_campaign_id", "ad_campaign_id"),
    )


class Ad(TimestampMixin, Base):
    """Leaf-level ad: Meta Ad / Google Ad / LinkedIn Creative."""

    __tablename__ = "ads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ad_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ad_groups.id", ondelete="CASCADE")
    )
    external_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(500))
    status: Mapped[AdEntityStatus] = mapped_column(
        Enum(AdEntityStatus), default=AdEntityStatus.unknown
    )

    ad_group: Mapped[AdGroup] = relationship(back_populates="ads")
    metrics: Mapped[list[AdMetric]] = relationship(
        back_populates="ad", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("ad_group_id", "external_id", name="uq_ad_group_ext"),
        Index("ix_ad_ad_group_id", "ad_group_id"),
    )


class AdMetric(TimestampMixin, Base):
    """Daily metrics for a single ad — wide-column layout."""

    __tablename__ = "ad_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ad_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ads.id", ondelete="CASCADE")
    )
    metric_date = mapped_column(Date, nullable=False)
    impressions: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    reach: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    clicks: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    spend: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    conversions: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    ctr: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    cpc: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)

    ad: Mapped[Ad] = relationship(back_populates="metrics")

    __table_args__ = (
        UniqueConstraint("ad_id", "metric_date", name="uq_ad_metric_ad_date"),
        Index("ix_ad_metric_date", "metric_date"),
    )
