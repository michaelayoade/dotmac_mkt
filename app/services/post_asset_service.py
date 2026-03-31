"""CRUD for the post_assets junction table."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, post_assets

logger = logging.getLogger(__name__)


class PostAssetService:
    """Manage post–asset associations (the post_assets junction table)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def link_asset(self, post_id: UUID, asset_id: UUID) -> None:
        """Link an asset to a post."""
        self.db.execute(insert(post_assets).values(post_id=post_id, asset_id=asset_id))
        self.db.flush()
        logger.info("Linked Asset %s to Post %s", asset_id, post_id)

    def unlink_asset(self, post_id: UUID, asset_id: UUID) -> None:
        """Unlink an asset from a post."""
        self.db.execute(
            delete(post_assets).where(
                post_assets.c.post_id == post_id,
                post_assets.c.asset_id == asset_id,
            )
        )
        self.db.flush()
        logger.info("Unlinked Asset %s from Post %s", asset_id, post_id)

    def list_assets_for_post(self, post_id: UUID) -> list[Asset]:
        """Return all assets linked to a post."""
        stmt = (
            select(Asset)
            .join(post_assets, Asset.id == post_assets.c.asset_id)
            .where(post_assets.c.post_id == post_id)
        )
        return list(self.db.scalars(stmt).all())

    def list_posts_for_asset(self, asset_id: UUID) -> list[UUID]:
        """Return post IDs linked to an asset."""
        stmt = select(post_assets.c.post_id).where(post_assets.c.asset_id == asset_id)
        return [row[0] for row in self.db.execute(stmt).all()]
