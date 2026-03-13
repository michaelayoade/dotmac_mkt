from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.channel import ChannelProvider, ChannelStatus


class ChannelBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    provider: ChannelProvider


class ChannelCreate(ChannelBase):
    pass


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    provider: ChannelProvider | None = Field(default=None)


class ChannelRead(ChannelBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    status: ChannelStatus
    external_account_id: str | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
