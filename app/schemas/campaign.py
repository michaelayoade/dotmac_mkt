from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.campaign import CampaignStatus


class CampaignBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None)
    status: CampaignStatus = Field(default=CampaignStatus.draft)
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None)
    status: CampaignStatus | None = Field(default=None)
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)


class CampaignRead(CampaignBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
