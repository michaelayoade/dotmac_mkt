from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.domain_settings import SettingDomain, SettingValueType


class DomainSettingBase(BaseModel):
    domain: SettingDomain
    key: str
    value_type: SettingValueType = SettingValueType.string
    value_text: str | None = None
    value_json: dict | list | bool | int | str | None = None
    is_secret: bool = False
    is_active: bool = True


class DomainSettingCreate(DomainSettingBase):
    pass


class DomainSettingUpdate(BaseModel):
    domain: SettingDomain | None = None
    key: str | None = None
    value_type: SettingValueType | None = None
    value_text: str | None = None
    value_json: dict | list | bool | int | str | None = None
    is_secret: bool | None = None
    is_active: bool | None = None


class DomainSettingRead(DomainSettingBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
