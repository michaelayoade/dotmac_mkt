import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import Channel, ChannelStatus
from app.schemas.channel import ChannelCreate

logger = logging.getLogger(__name__)


class ChannelService:
    """Service for managing marketing channels."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: UUID) -> Channel | None:
        return self.db.get(Channel, id)

    def list_all(self, *, limit: int = 50) -> list[Channel]:
        stmt = select(Channel).order_by(Channel.name).limit(limit)
        return list(self.db.scalars(stmt).all())

    def create(self, data: ChannelCreate) -> Channel:
        record = Channel(**data.model_dump())
        self.db.add(record)
        self.db.flush()
        logger.info("Created Channel: %s", record.id)
        return record

    def update_status(self, id: UUID, status: ChannelStatus) -> Channel:
        record = self.db.get(Channel, id)
        if record is None:
            raise ValueError(f"Channel {id} not found")
        record.status = status
        self.db.flush()
        logger.info("Updated Channel %s status to %s", record.id, status.value)
        return record

    def store_credentials(self, id: UUID, encrypted: bytes) -> None:
        record = self.db.get(Channel, id)
        if record is None:
            raise ValueError(f"Channel {id} not found")
        record.credentials_encrypted = encrypted
        self.db.flush()
        logger.info("Stored credentials for Channel: %s", record.id)

    def get_credentials(self, id: UUID) -> bytes | None:
        record = self.db.get(Channel, id)
        if record is None:
            raise ValueError(f"Channel {id} not found")
        return record.credentials_encrypted

    def update_last_synced(self, id: UUID) -> None:
        record = self.db.get(Channel, id)
        if record is None:
            raise ValueError(f"Channel {id} not found")
        record.last_synced_at = datetime.now(UTC)
        self.db.flush()
        logger.info("Updated last_synced_at for Channel: %s", record.id)
