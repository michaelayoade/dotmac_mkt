import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.campaign import Campaign, CampaignStatus
from app.schemas.campaign import CampaignCreate, CampaignUpdate

logger = logging.getLogger(__name__)


class CampaignService:
    """Service for managing marketing campaigns."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: UUID) -> Campaign | None:
        return self.db.get(Campaign, id)

    def list_all(
        self,
        *,
        status: CampaignStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Campaign]:
        stmt = select(Campaign)
        if status is not None:
            stmt = stmt.where(Campaign.status == status)
        stmt = stmt.order_by(Campaign.created_at.desc()).offset(offset).limit(limit)
        return list(self.db.scalars(stmt).all())

    def count(self, *, status: CampaignStatus | None = None) -> int:
        stmt = select(func.count(Campaign.id))
        if status is not None:
            stmt = stmt.where(Campaign.status == status)
        result = self.db.scalar(stmt)
        return result or 0

    def create(self, data: CampaignCreate, created_by: UUID) -> Campaign:
        record = Campaign(**data.model_dump(), created_by=created_by)
        self.db.add(record)
        self.db.flush()
        logger.info("Created Campaign: %s", record.id)
        return record

    def update(self, id: UUID, data: CampaignUpdate) -> Campaign:
        record = self.db.get(Campaign, id)
        if record is None:
            raise ValueError(f"Campaign {id} not found")
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(record, field, value)
        self.db.flush()
        logger.info("Updated Campaign: %s", record.id)
        return record

    def archive(self, id: UUID) -> Campaign:
        record = self.db.get(Campaign, id)
        if record is None:
            raise ValueError(f"Campaign {id} not found")
        record.status = CampaignStatus.archived
        self.db.flush()
        logger.info("Archived Campaign: %s", record.id)
        return record
