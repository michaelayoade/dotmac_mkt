import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SettingValueType(enum.Enum):
    string = "string"
    integer = "integer"
    boolean = "boolean"
    json = "json"


class SettingDomain(enum.Enum):
    auth = "auth"
    audit = "audit"
    scheduler = "scheduler"
    billing = "billing"


class DomainSetting(Base):
    __tablename__ = "domain_settings"
    __table_args__ = (
        UniqueConstraint("domain", "key", name="uq_domain_settings_domain_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    domain: Mapped[SettingDomain] = mapped_column(Enum(SettingDomain), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value_type: Mapped[SettingValueType] = mapped_column(
        Enum(SettingValueType), default=SettingValueType.string
    )
    value_text: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[dict | None] = mapped_column(JSON)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
