import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.post import Post, PostStatus
from app.models.post_delivery import PostDelivery, PostDeliveryStatus
from app.schemas.post import PostCreate, PostUpdate

logger = logging.getLogger(__name__)


def post_recency_sort_expr():
    return func.coalesce(Post.published_at, Post.scheduled_at, Post.created_at)


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
        stmt = (
            stmt.order_by(
                post_recency_sort_expr().desc(),
                Post.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
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
        record = Post(
            **data.model_dump(exclude={"channel_ids"}),
            created_by=created_by,
        )
        self.db.add(record)
        self.db.flush()
        logger.info("Created Post: %s", record.id)
        return record

    def replace_deliveries(
        self,
        post: Post,
        *,
        channel_ids: list[UUID],
        content: str | None = None,
        content_overrides: dict[UUID, str] | None = None,
    ) -> None:
        selected = list(dict.fromkeys(channel_ids))
        existing = {delivery.channel_id: delivery for delivery in post.deliveries}
        overrides = content_overrides or {}

        for channel_id in list(existing):
            if channel_id not in selected:
                self.db.delete(existing[channel_id])

        for channel_id in selected:
            override = (overrides.get(channel_id) or "").strip() or None
            if channel_id in existing:
                delivery = existing[channel_id]
                delivery.content_override = override
                if delivery.status != PostDeliveryStatus.published:
                    delivery.status = (
                        PostDeliveryStatus.planned
                        if post.status == PostStatus.planned
                        else PostDeliveryStatus.draft
                    )
                continue
            channel = self.db.get(Channel, channel_id)
            if channel is None:
                continue
            self.db.add(
                PostDelivery(
                    post_id=post.id,
                    channel_id=channel_id,
                    provider=channel.provider,
                    content_override=override or content,
                    status=(
                        PostDeliveryStatus.planned
                        if post.status == PostStatus.planned
                        else PostDeliveryStatus.draft
                    ),
                )
            )
        self.db.flush()

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
