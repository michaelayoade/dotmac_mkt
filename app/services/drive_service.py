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

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            logger.error("google-api-python-client not installed")
            return {"created": 0, "updated": 0, "missing": 0}

        # Build credentials from stored OAuth tokens
        from app.services.credential_service import CredentialService

        cred_svc = CredentialService()
        token_data = self._get_drive_tokens(cred_svc)
        if not token_data:
            logger.warning("No Drive OAuth tokens found, skipping sync")
            return {"created": 0, "updated": 0, "missing": 0}

        creds = Credentials(
            token=token_data.get("access_token", ""),
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",  # noqa: S106
            client_id=settings.google_drive_client_id,
            client_secret=settings.google_drive_client_secret,
        )

        service = build("drive", "v3", credentials=creds)

        logger.info("Drive sync started for folder %s", settings.google_drive_folder_id)
        counts = {"created": 0, "updated": 0, "missing": 0}

        # List files in the configured folder
        drive_file_ids: set[str] = set()
        page_token = None
        while True:
            resp = (
                service.files()
                .list(
                    q=f"'{settings.google_drive_folder_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType, size, webViewLink, thumbnailLink)",
                    pageSize=100,
                    pageToken=page_token,
                )
                .execute()
            )

            for f in resp.get("files", []):
                drive_file_ids.add(f["id"])
                self._upsert_drive_file(f, counts)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        # Mark assets whose drive_file_id is no longer in the folder
        self._mark_removed_assets(drive_file_ids, counts)

        return counts

    def _get_drive_tokens(self, cred_svc) -> dict | None:
        """Retrieve stored Drive OAuth tokens from any Google channel."""
        from app.models.channel import Channel, ChannelProvider

        for provider in (ChannelProvider.google_ads, ChannelProvider.google_analytics):
            stmt = select(Channel).where(
                Channel.provider == provider,
                Channel.credentials_encrypted.isnot(None),
            )
            channel = self.db.scalar(stmt)
            if channel and channel.credentials_encrypted:
                try:
                    return cred_svc.decrypt(channel.credentials_encrypted)
                except (ValueError, TypeError):
                    continue
        return None

    def _upsert_drive_file(self, file_data: dict, counts: dict) -> None:
        """Create or update an asset from a Drive file listing entry."""
        file_id = file_data["id"]
        name = file_data.get("name", "Untitled")
        mime_type = file_data.get("mimeType", "")
        size = int(file_data.get("size", 0))
        web_view_link = file_data.get("webViewLink", "")
        thumbnail_link = file_data.get("thumbnailLink")

        # Check if asset already exists
        stmt = select(Asset).where(Asset.drive_file_id == file_id)
        existing = self.db.scalar(stmt)

        if existing:
            # Update metadata
            existing.name = name
            existing.mime_type = mime_type
            if size:
                existing.file_size = size
            if web_view_link:
                existing.drive_url = web_view_link
            if thumbnail_link:
                existing.thumbnail_url = thumbnail_link
            existing.drive_status = DriveStatus.active
            existing.last_verified_at = datetime.now(UTC)
            self.db.flush()
            counts["updated"] += 1
        else:
            self.create_asset_from_drive(
                file_id=file_id,
                name=name,
                mime_type=mime_type,
                size=size,
                web_view_link=web_view_link,
                thumbnail_link=thumbnail_link,
            )
            counts["created"] += 1

    def _mark_removed_assets(self, active_file_ids: set[str], counts: dict) -> None:
        """Mark assets that are no longer in the Drive folder as missing."""
        stmt = select(Asset).where(
            Asset.drive_file_id.isnot(None),
            Asset.drive_status == DriveStatus.active,
        )
        assets = list(self.db.scalars(stmt).all())
        for asset in assets:
            if asset.drive_file_id not in active_file_ids:
                asset.drive_status = DriveStatus.missing
                asset.last_verified_at = datetime.now(UTC)
                counts["missing"] += 1
                logger.warning(
                    "Asset no longer in Drive folder: %s (%s)",
                    asset.name,
                    asset.drive_file_id,
                )
        if counts["missing"]:
            self.db.flush()

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
