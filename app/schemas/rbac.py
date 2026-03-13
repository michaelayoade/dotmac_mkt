from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RoleBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    is_active: bool = True


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = None
    is_active: bool | None = None


class RoleRead(RoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class PermissionBase(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    description: str | None = None
    is_active: bool = True


class PermissionCreate(PermissionBase):
    pass


class PermissionUpdate(BaseModel):
    key: str | None = Field(default=None, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class PermissionRead(PermissionBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class RolePermissionBase(BaseModel):
    role_id: UUID
    permission_id: UUID


class RolePermissionCreate(RolePermissionBase):
    pass


class RolePermissionUpdate(BaseModel):
    role_id: UUID | None = None
    permission_id: UUID | None = None


class RolePermissionRead(RolePermissionBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class PersonRoleBase(BaseModel):
    person_id: UUID
    role_id: UUID


class PersonRoleCreate(PersonRoleBase):
    pass


class PersonRoleUpdate(BaseModel):
    person_id: UUID | None = None
    role_id: UUID | None = None


class PersonRoleRead(PersonRoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assigned_at: datetime
