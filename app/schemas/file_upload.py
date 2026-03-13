from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FileUploadCreate(BaseModel):
    category: str = Field(default="document", max_length=40)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=120)
    metadata_: dict | None = Field(default=None, serialization_alias="metadata")


class FileUploadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    uploaded_by: UUID | None = None
    original_filename: str
    content_type: str
    file_size: int
    storage_backend: str
    url: str | None = None
    category: str
    entity_type: str | None = None
    entity_id: str | None = None
    status: str
    is_active: bool
    metadata_: dict | None = Field(default=None, serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime
