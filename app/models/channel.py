from __future__ import annotations

import enum
import uuid

from sqlalchemy import DateTime, Enum, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class ChannelProvider(str, enum.Enum):
    meta_instagram = "meta_instagram"
    meta_facebook = "meta_facebook"
    twitter = "twitter"
    linkedin = "linkedin"
    google_ads = "google_ads"
    google_analytics = "google_analytics"


class ChannelStatus(str, enum.Enum):
    connected = "connected"
    disconnected = "disconnected"
    error = "error"


class Channel(TimestampMixin, Base):
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[ChannelProvider] = mapped_column(Enum(ChannelProvider))
    status: Mapped[ChannelStatus] = mapped_column(
        Enum(ChannelStatus), default=ChannelStatus.disconnected
    )
    credentials_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    external_account_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    last_synced_at = mapped_column(DateTime(timezone=True), nullable=True)

    posts = relationship("Post", back_populates="channel")
    metrics = relationship(
        "ChannelMetric", back_populates="channel", cascade="all, delete-orphan"
    )
