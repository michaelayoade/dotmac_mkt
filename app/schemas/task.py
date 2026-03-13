from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import TaskStatus


class TaskBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None)
    status: TaskStatus = Field(default=TaskStatus.todo)
    campaign_id: UUID
    assignee_id: UUID | None = Field(default=None)
    due_date: date | None = Field(default=None)


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None)
    status: TaskStatus | None = Field(default=None)
    campaign_id: UUID | None = Field(default=None)
    assignee_id: UUID | None = Field(default=None)
    due_date: date | None = Field(default=None)


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
