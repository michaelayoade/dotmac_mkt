"""Pydantic schemas for ad campaign tracking."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.ad_campaign import AdEntityStatus, AdPlatform


class AdMetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ad_id: UUID
    metric_date: date
    impressions: float
    reach: float
    clicks: float
    spend: float
    conversions: float
    ctr: float
    cpc: float
    currency_code: str | None


class AdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str
    name: str
    status: AdEntityStatus
    created_at: datetime
    updated_at: datetime


class AdGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str
    name: str
    status: AdEntityStatus
    ads: list[AdRead] = []


class AdCampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: AdPlatform
    external_id: str
    name: str
    status: AdEntityStatus
    campaign_id: UUID | None
    ad_groups: list[AdGroupRead] = []
    created_at: datetime
    updated_at: datetime


class AdCampaignLinkRequest(BaseModel):
    campaign_id: UUID | None = None
