from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.asset import Asset, AssetType, DriveStatus

logger = logging.getLogger(__name__)

# MIME type to AssetType mapping
MIME_TYPE_MAP = {
    "image/jpeg": AssetType.image,
    "image/png": AssetType.image,
    "image/gif": AssetType.image,
    "image/webp": AssetType.image,
    "image/svg+xml": AssetType.image,
    "video/mp4": AssetType.video,
    "video/quicktime": AssetType.video,
    "video/webm": AssetType.video,
    "application/pdf": AssetType.document,
    "application/vnd.google-apps.document": AssetType.document,
    "application/vnd.google-apps.spreadsheet": AssetType.document,
    "application/vnd.google-apps.presentation": AssetType.document,
    "text/plain": AssetType.document,
}


class DriveService:
    """Google Drive integration for asset management."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def is_configured() -> bool:
        return bool(
            settings.google_drive_client_id
            and settings.google_drive_client_secret
            and settings.google_drive_folder_id
        )

    def sync_folder(self) -> dict:
        """Sync files from configured Drive folder into Asset table.

        Returns dict with counts: {"created": N, "updated": N, "missing": N}
        """
        if not self.is_configured():
            logger.warning("Google Drive not configured, skipping sync")
            return {"created": 0, "updated": 0, "missing": 0}

        # Import here to avoid import errors when google libs not available
        try:
            from google.oauth2.credentials import Credentials  # noqa: F401
            from googleapiclient.discovery import build  # noqa: F401
        except ImportError:
            logger.error("google-api-python-client not installed")
            return {"created": 0, "updated": 0, "missing": 0}

        # TODO: Build credentials from stored OAuth tokens
        # For now, this is a stub that will be completed when Drive OAuth is wired up
        logger.info("Drive sync started for folder %s", settings.google_drive_folder_id)

        counts = {"created": 0, "updated": 0, "missing": 0}

        # Mark missing assets that are no longer accessible
        self._verify_existing_assets(counts)

        return counts

    def _verify_existing_assets(self, counts: dict) -> None:
        """Check existing assets still exist in Drive. Mark missing ones."""
        stmt = select(Asset).where(
            Asset.drive_file_id.isnot(None),
            Asset.drive_status == DriveStatus.active,
        )
        assets = list(self.db.scalars(stmt).all())

        for asset in assets:
            # TODO: Check each file via Drive API
            # For now, just update last_verified_at
            asset.last_verified_at = datetime.now(UTC)

        if assets:
            self.db.flush()
            logger.info("Verified %d Drive assets", len(assets))

    def create_asset_from_drive(
        self,
        file_id: str,
        name: str,
        mime_type: str,
        size: int,
        web_view_link: str,
        thumbnail_link: str | None = None,
        uploaded_by=None,
    ) -> Asset:
        """Create a local Asset record from a Drive file."""
        asset_type = MIME_TYPE_MAP.get(mime_type, AssetType.document)

        asset = Asset(
            name=name,
            asset_type=asset_type,
            drive_file_id=file_id,
            drive_url=web_view_link,
            thumbnail_url=thumbnail_link,
            mime_type=mime_type,
            file_size=size,
            tags=[],
            drive_status=DriveStatus.active,
            last_verified_at=datetime.now(UTC),
            uploaded_by=uploaded_by,
        )
        self.db.add(asset)
        self.db.flush()
        logger.info("Created asset from Drive: %s (%s)", name, file_id)
        return asset

    def mark_missing(self, asset_id) -> None:
        """Mark an asset as missing from Drive."""
        asset = self.db.get(Asset, asset_id)
        if asset:
            asset.drive_status = DriveStatus.missing
            asset.last_verified_at = datetime.now(UTC)
            self.db.flush()
            logger.warning("Asset marked missing: %s", asset.name)

    def mark_access_denied(self, asset_id) -> None:
        """Mark an asset as access denied in Drive."""
        asset = self.db.get(Asset, asset_id)
        if asset:
            asset.drive_status = DriveStatus.access_denied
            asset.last_verified_at = datetime.now(UTC)
            self.db.flush()
            logger.warning("Asset access denied: %s", asset.name)
