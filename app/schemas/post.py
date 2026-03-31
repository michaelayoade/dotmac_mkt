from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.post import PostStatus


class PostBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=300)
    content: str | None = Field(default=None)
    status: PostStatus = Field(default=PostStatus.draft)
    campaign_id: UUID
    channel_id: UUID | None = Field(default=None)
    scheduled_at: datetime | None = Field(default=None)
    channel_ids: list[UUID] = Field(default_factory=list)


class PostCreate(PostBase):
    pass


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    content: str | None = Field(default=None)
    status: PostStatus | None = Field(default=None)
    campaign_id: UUID | None = Field(default=None)
    channel_id: UUID | None = Field(default=None)
    scheduled_at: datetime | None = Field(default=None)


class PostRead(PostBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    published_at: datetime | None
    external_post_id: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
