import logging
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, AssetType, DriveStatus
from app.models.campaign import campaign_assets
from app.schemas.asset import AssetCreate, AssetUpdate

logger = logging.getLogger(__name__)


class AssetService:
    """Service for managing marketing assets."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: UUID) -> Asset | None:
        return self.db.get(Asset, id)

    def list_all(
        self,
        *,
        asset_type: AssetType | None = None,
        campaign_id: UUID | None = None,
        include_missing: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Asset]:
        stmt = select(Asset)
        if not include_missing:
            stmt = stmt.where(Asset.drive_status != DriveStatus.missing)
        if asset_type is not None:
            stmt = stmt.where(Asset.asset_type == asset_type)
        if campaign_id is not None:
            stmt = stmt.join(
                campaign_assets, Asset.id == campaign_assets.c.asset_id
            ).where(campaign_assets.c.campaign_id == campaign_id)
        stmt = stmt.order_by(Asset.created_at.desc()).offset(offset).limit(limit)
        return list(self.db.scalars(stmt).all())

    def count(
        self,
        *,
        asset_type: AssetType | None = None,
        campaign_id: UUID | None = None,
        include_missing: bool = False,
    ) -> int:
        stmt = select(func.count(Asset.id))
        if not include_missing:
            stmt = stmt.where(Asset.drive_status != DriveStatus.missing)
        if asset_type is not None:
            stmt = stmt.where(Asset.asset_type == asset_type)
        if campaign_id is not None:
            stmt = stmt.join(
                campaign_assets, Asset.id == campaign_assets.c.asset_id
            ).where(campaign_assets.c.campaign_id == campaign_id)
        result = self.db.scalar(stmt)
        return result or 0

    def create(self, data: AssetCreate, uploaded_by: UUID | None = None) -> Asset:
        record = Asset(**data.model_dump(), uploaded_by=uploaded_by)
        self.db.add(record)
        self.db.flush()
        logger.info("Created Asset: %s", record.id)
        return record

    def update(self, id: UUID, data: AssetUpdate) -> Asset:
        record = self.db.get(Asset, id)
        if record is None:
            raise ValueError(f"Asset {id} not found")
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(record, field, value)
        self.db.flush()
        logger.info("Updated Asset: %s", record.id)
        return record

    def delete(self, id: UUID) -> None:
        """Soft-delete an asset by marking drive_status as missing."""
        record = self.db.get(Asset, id)
        if record is None:
            raise ValueError(f"Asset {id} not found")
        record.drive_status = DriveStatus.missing
        self.db.flush()
        logger.info("Soft-deleted Asset: %s", id)

    def link_to_campaign(self, asset_id: UUID, campaign_id: UUID) -> None:
        stmt = campaign_assets.insert().values(
            asset_id=asset_id, campaign_id=campaign_id
        )
        self.db.execute(stmt)
        self.db.flush()
        logger.info(
            "Linked Asset %s to Campaign %s", asset_id, campaign_id
        )

    def unlink_from_campaign(self, asset_id: UUID, campaign_id: UUID) -> None:
        stmt = delete(campaign_assets).where(
            campaign_assets.c.asset_id == asset_id,
            campaign_assets.c.campaign_id == campaign_id,
        )
        self.db.execute(stmt)
        self.db.flush()
        logger.info(
            "Unlinked Asset %s from Campaign %s", asset_id, campaign_id
        )
