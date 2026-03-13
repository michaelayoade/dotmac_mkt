from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationCreate(BaseModel):
    recipient_id: UUID
    sender_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    message: str | None = None
    type: str = "info"
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=120)
    action_url: str | None = Field(default=None, max_length=512)


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    recipient_id: UUID
    sender_id: UUID | None = None
    title: str
    message: str | None = None
    type: str
    entity_type: str | None = None
    entity_id: str | None = None
    action_url: str | None = None
    is_read: bool
    read_at: datetime | None = None
    is_active: bool
    metadata_: dict | None = Field(default=None, serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


class UnreadCountResponse(BaseModel):
    count: int
