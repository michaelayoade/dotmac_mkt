from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin
from app.models.channel import ChannelProvider


class PostDeliveryStatus(str, enum.Enum):
    draft = "draft"
    planned = "planned"
    published = "published"
    failed = "failed"


class PostDelivery(TimestampMixin, Base):
    __tablename__ = "post_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE")
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE")
    )
    provider: Mapped[ChannelProvider] = mapped_column(Enum(ChannelProvider))
    content_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PostDeliveryStatus] = mapped_column(
        Enum(PostDeliveryStatus), default=PostDeliveryStatus.draft
    )
    external_post_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    post = relationship("Post", back_populates="deliveries")
    channel = relationship("Channel", back_populates="post_deliveries")

    __table_args__ = (
        Index("ix_post_delivery_post_id", "post_id"),
        Index("ix_post_delivery_channel_id", "channel_id"),
    )
