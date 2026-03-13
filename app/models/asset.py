from __future__ import annotations

import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class AssetType(str, enum.Enum):
    image = "image"
    video = "video"
    document = "document"
    template = "template"
    brand_guide = "brand_guide"


class DriveStatus(str, enum.Enum):
    active = "active"
    missing = "missing"
    access_denied = "access_denied"


post_assets = Table(
    "post_assets",
    Base.metadata,
    Column(
        "post_id",
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "asset_id",
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(300))
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType))
    drive_file_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    drive_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags = mapped_column(JSONB, default=list)
    drive_status: Mapped[DriveStatus] = mapped_column(
        Enum(DriveStatus), default=DriveStatus.active
    )
    last_verified_at = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id"), nullable=True
    )

    campaigns = relationship(
        "Campaign",
        secondary="campaign_assets",
        back_populates="assets",
    )
    posts = relationship("Post", secondary=post_assets, back_populates="assets")
