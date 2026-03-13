import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.post import Post
from app.schemas.post import PostCreate, PostUpdate

logger = logging.getLogger(__name__)


class PostService:
    """Service for managing social media posts."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: UUID) -> Post | None:
        return self.db.get(Post, id)

    def list_all(
        self,
        *,
        campaign_id: UUID | None = None,
        channel_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Post]:
        stmt = select(Post)
        if campaign_id is not None:
            stmt = stmt.where(Post.campaign_id == campaign_id)
        if channel_id is not None:
            stmt = stmt.where(Post.channel_id == channel_id)
        stmt = stmt.order_by(Post.created_at.desc()).offset(offset).limit(limit)
        return list(self.db.scalars(stmt).all())

    def list_scheduled(self, *, days_ahead: int = 7) -> list[Post]:
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=days_ahead)
        stmt = (
            select(Post)
            .where(Post.scheduled_at.isnot(None))
            .where(Post.scheduled_at >= now)
            .where(Post.scheduled_at <= cutoff)
            .order_by(Post.scheduled_at)
        )
        return list(self.db.scalars(stmt).all())

    def count(self, *, campaign_id: UUID | None = None) -> int:
        stmt = select(func.count(Post.id))
        if campaign_id is not None:
            stmt = stmt.where(Post.campaign_id == campaign_id)
        result = self.db.scalar(stmt)
        return result or 0

    def create(self, data: PostCreate, created_by: UUID) -> Post:
        record = Post(**data.model_dump(), created_by=created_by)
        self.db.add(record)
        self.db.flush()
        logger.info("Created Post: %s", record.id)
        return record

    def update(self, id: UUID, data: PostUpdate) -> Post:
        record = self.db.get(Post, id)
        if record is None:
            raise ValueError(f"Post {id} not found")
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(record, field, value)
        self.db.flush()
        logger.info("Updated Post: %s", record.id)
        return record

    def reschedule(self, id: UUID, scheduled_at: datetime) -> Post:
        record = self.db.get(Post, id)
        if record is None:
            raise ValueError(f"Post {id} not found")
        record.scheduled_at = scheduled_at
        self.db.flush()
        logger.info("Rescheduled Post %s to %s", record.id, scheduled_at)
        return record

    def delete(self, id: UUID) -> None:
        record = self.db.get(Post, id)
        if record is None:
            raise ValueError(f"Post {id} not found")
        self.db.delete(record)
        self.db.flush()
        logger.info("Deleted Post: %s", id)
