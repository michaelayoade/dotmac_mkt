from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.asset import AssetType, DriveStatus


class AssetBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=300)
    asset_type: AssetType
    drive_file_id: str | None = Field(default=None)
    drive_url: str | None = Field(default=None)
    thumbnail_url: str | None = Field(default=None)
    mime_type: str | None = Field(default=None)
    file_size: int | None = Field(default=None)
    tags: list[str] = Field(default_factory=list)


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    asset_type: AssetType | None = Field(default=None)
    drive_file_id: str | None = Field(default=None)
    drive_url: str | None = Field(default=None)
    thumbnail_url: str | None = Field(default=None)
    mime_type: str | None = Field(default=None)
    file_size: int | None = Field(default=None)
    tags: list[str] | None = Field(default=None)


class AssetRead(AssetBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    drive_status: DriveStatus | None
    last_verified_at: datetime | None
    uploaded_by: UUID | None
    created_at: datetime
    updated_at: datetime
