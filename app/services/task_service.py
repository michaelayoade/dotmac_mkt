import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.task import Task, TaskStatus
from app.schemas.task import TaskCreate as MktTaskCreate
from app.schemas.task import TaskUpdate as MktTaskUpdate

logger = logging.getLogger(__name__)


class MktTaskService:
    """Service for managing marketing tasks."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: UUID) -> Task | None:
        return self.db.get(Task, id)

    def list_all(
        self,
        *,
        campaign_id: UUID | None = None,
        status: TaskStatus | None = None,
        assignee_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        stmt = select(Task)
        if campaign_id is not None:
            stmt = stmt.where(Task.campaign_id == campaign_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if assignee_id is not None:
            stmt = stmt.where(Task.assignee_id == assignee_id)
        stmt = stmt.order_by(Task.created_at.desc()).offset(offset).limit(limit)
        return list(self.db.scalars(stmt).all())

    def count(
        self,
        *,
        campaign_id: UUID | None = None,
        status: TaskStatus | None = None,
    ) -> int:
        stmt = select(func.count(Task.id))
        if campaign_id is not None:
            stmt = stmt.where(Task.campaign_id == campaign_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        result = self.db.scalar(stmt)
        return result or 0

    def create(self, data: MktTaskCreate, created_by: UUID) -> Task:
        record = Task(**data.model_dump(), created_by=created_by)
        self.db.add(record)
        self.db.flush()
        logger.info("Created Task: %s", record.id)
        return record

    def update(self, id: UUID, data: MktTaskUpdate) -> Task:
        record = self.db.get(Task, id)
        if record is None:
            raise ValueError(f"Task {id} not found")
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(record, field, value)
        self.db.flush()
        logger.info("Updated Task: %s", record.id)
        return record

    def delete(self, id: UUID) -> None:
        record = self.db.get(Task, id)
        if record is None:
            raise ValueError(f"Task {id} not found")
        self.db.delete(record)
        self.db.flush()
        logger.info("Deleted Task: %s", id)
