from __future__ import annotations

import enum
import uuid

from sqlalchemy import Column, Date, Enum, ForeignKey, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class CampaignMemberRole(str, enum.Enum):
    owner = "owner"
    contributor = "contributor"


campaign_assets = Table(
    "campaign_assets",
    Base.metadata,
    Column(
        "campaign_id",
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "asset_id",
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("sort_order", Integer, default=0),
)


campaign_members = Table(
    "campaign_members",
    Base.metadata,
    Column(
        "campaign_id",
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "person_id",
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role",
        Enum(CampaignMemberRole),
        default=CampaignMemberRole.contributor,
    ),
)


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus), default=CampaignStatus.draft
    )
    start_date = mapped_column(Date, nullable=True)
    end_date = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id")
    )

    posts = relationship(
        "Post", back_populates="campaign", cascade="all, delete-orphan"
    )
    tasks = relationship(
        "Task", back_populates="campaign", cascade="all, delete-orphan"
    )
    assets = relationship(
        "Asset", secondary=campaign_assets, back_populates="campaigns"
    )
    members = relationship("Person", secondary=campaign_members)
