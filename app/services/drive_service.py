from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.asset import Asset, AssetType, DriveStatus
from app.services.marketing_runtime import get_marketing_value

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

    @staticmethod
    def _allowed_upload_types() -> set[str]:
        return {
            item.strip()
            for item in settings.upload_allowed_types.split(",")
            if item.strip()
        }

    @staticmethod
    def _validate_upload(
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> None:
        if not filename:
            raise ValueError("Please select a file to upload")
        if not content:
            raise ValueError("Uploaded file is empty")
        if len(content) > settings.upload_max_size_bytes:
            raise ValueError(
                f"File too large. Maximum size: {settings.upload_max_size_bytes // 1024 // 1024}MB"
            )
        allowed = DriveService._allowed_upload_types()
        if content_type not in allowed:
            raise ValueError(
                "Invalid file type. Allowed: " + ", ".join(sorted(allowed))
            )

    def _drive_client_config(self) -> tuple[str, str, str]:
        return (
            get_marketing_value("google_drive_client_id", self.db),
            get_marketing_value("google_drive_client_secret", self.db),
            get_marketing_value("google_drive_folder_id", self.db),
        )

    def _token_data(self) -> dict | None:
        from app.services.credential_service import CredentialService

        cred_svc = CredentialService()
        return self._get_drive_tokens(cred_svc)

    def _build_drive_service(self):
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("google-api-python-client not installed") from exc

        client_id, client_secret, _ = self._drive_client_config()
        if not (client_id and client_secret):
            raise RuntimeError("Google Drive credentials are not configured")

        token_data = self._token_data()
        if not token_data:
            raise RuntimeError("No Drive OAuth tokens found")

        creds = Credentials(
            token=token_data.get("access_token", ""),
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",  # noqa: S106
            client_id=client_id,
            client_secret=client_secret,
            scopes=(token_data.get("scope") or "").split(),
        )
        return build("drive", "v3", credentials=creds)

    def sync_folder(self) -> dict:
        """Sync files from configured Drive folder into Asset table.

        Returns dict with counts: {"created": N, "updated": N, "missing": N}
        """
        _, _, folder_id = self._drive_client_config()
        if not folder_id:
            logger.warning("Google Drive not configured, skipping sync")
            return {"created": 0, "updated": 0, "missing": 0}

        try:
            service = self._build_drive_service()
        except RuntimeError as exc:
            logger.warning("%s, skipping sync", exc)
            return {"created": 0, "updated": 0, "missing": 0}

        logger.info("Drive sync started for folder %s", folder_id)
        counts = {"created": 0, "updated": 0, "missing": 0}

        # List files in the configured folder
        drive_file_ids: set[str] = set()
        page_token = None
        while True:
            resp = (
                service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
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

    def upload_asset_file(
        self,
        *,
        filename: str,
        drive_filename: str | None = None,
        folder_id: str | None = None,
        content_type: str,
        content: bytes,
        uploaded_by=None,
    ) -> Asset:
        self._validate_upload(
            filename=filename,
            content_type=content_type,
            content=content,
        )
        _, _, default_folder_id = self._drive_client_config()
        target_folder_id = (folder_id or default_folder_id or "").strip()
        if not target_folder_id:
            raise RuntimeError("Google Drive folder is not configured")

        token_data = self._token_data()
        scopes = set((token_data or {}).get("scope", "").split())
        if "https://www.googleapis.com/auth/drive.file" not in scopes:
            raise RuntimeError(
                "Connected Google account does not have Drive upload permission. Reconnect Google Ads or Google Analytics to grant drive.file scope."
            )

        service = self._build_drive_service()
        try:
            from googleapiclient.http import MediaIoBaseUpload
        except ImportError as exc:
            raise RuntimeError("google-api-python-client not installed") from exc

        media = MediaIoBaseUpload(
            io.BytesIO(content),
            mimetype=content_type,
            resumable=False,
        )
        target_name = self._normalize_drive_filename(
            display_name=drive_filename,
            original_filename=filename,
        )
        created = (
            service.files()
            .create(
                body={"name": target_name, "parents": [target_folder_id]},
                media_body=media,
                fields="id,name,mimeType,size,webViewLink,thumbnailLink",
            )
            .execute()
        )
        logger.info("Uploaded asset to Drive: %s (%s)", target_name, created.get("id"))
        return self.create_asset_from_drive(
            file_id=created["id"],
            name=drive_filename or target_name,
            mime_type=created.get("mimeType", content_type),
            size=int(created.get("size", len(content))),
            web_view_link=created.get("webViewLink", ""),
            thumbnail_link=created.get("thumbnailLink"),
            uploaded_by=uploaded_by,
        )

    def list_upload_folders(self) -> list[dict[str, str]]:
        _, _, parent_folder_id = self._drive_client_config()
        if not parent_folder_id:
            return []
        service = self._build_drive_service()

        parent = (
            service.files().get(fileId=parent_folder_id, fields="id,name").execute()
        )
        response = (
            service.files()
            .list(
                q=(
                    f"'{parent_folder_id}' in parents "
                    "and mimeType = 'application/vnd.google-apps.folder' "
                    "and trashed = false"
                ),
                fields="files(id,name)",
                pageSize=100,
                orderBy="name",
            )
            .execute()
        )
        folders = [
            {
                "id": parent["id"],
                "name": f"{parent.get('name', 'Default Folder')} (Default)",
            }
        ]
        folders.extend(
            {"id": item["id"], "name": item.get("name", item["id"])}
            for item in response.get("files", [])
        )
        return folders

    def search_folders(self, *, query: str, limit: int = 8) -> list[dict[str, str]]:
        _, _, parent_folder_id = self._drive_client_config()
        if parent_folder_id and not query.strip():
            return self.list_upload_folders()[: max(1, min(limit, 25))]
        service = self._build_drive_service()
        escaped = query.replace("\\", "\\\\").replace("'", "\\'")
        if parent_folder_id:
            q = (
                f"'{parent_folder_id}' in parents "
                "and mimeType = 'application/vnd.google-apps.folder' "
                "and trashed = false "
                f"and name contains '{escaped}'"
            )
        else:
            q = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            if escaped:
                q += f" and name contains '{escaped}'"
        response = (
            service.files()
            .list(
                q=q,
                fields="files(id,name)",
                pageSize=max(1, min(limit, 25)),
                orderBy="name",
            )
            .execute()
        )
        return [
            {"id": item["id"], "name": item.get("name", item["id"])}
            for item in response.get("files", [])
        ]

    def get_folder(self, *, folder_id: str) -> dict[str, str] | None:
        if not folder_id:
            return None
        service = self._build_drive_service()
        try:
            folder = (
                service.files()
                .get(fileId=folder_id, fields="id,name,mimeType")
                .execute()
            )
        except Exception:
            return None
        if folder.get("mimeType") != "application/vnd.google-apps.folder":
            return None
        return {"id": folder["id"], "name": folder.get("name", folder["id"])}

    def rename_asset_file(self, *, file_id: str, display_name: str) -> dict:
        if not file_id:
            raise RuntimeError("Drive file ID is required")
        service = self._build_drive_service()
        current = (
            service.files().get(fileId=file_id, fields="id,name,mimeType").execute()
        )
        target_name = self._normalize_drive_filename(
            display_name=display_name,
            original_filename=current.get("name", display_name),
        )
        updated = (
            service.files()
            .update(
                fileId=file_id, body={"name": target_name}, fields="id,name,mimeType"
            )
            .execute()
        )
        logger.info("Renamed Drive asset: %s -> %s", file_id, target_name)
        return updated

    def delete_asset_file(self, *, file_id: str) -> None:
        if not file_id:
            return
        service = self._build_drive_service()
        service.files().delete(fileId=file_id).execute()
        logger.info("Deleted Drive asset: %s", file_id)

    @staticmethod
    def _normalize_drive_filename(
        *,
        display_name: str | None,
        original_filename: str,
    ) -> str:
        cleaned = (display_name or "").strip()
        if not cleaned:
            return original_filename
        suffix = Path(original_filename).suffix
        if suffix and not cleaned.lower().endswith(suffix.lower()):
            return f"{cleaned}{suffix}"
        return cleaned

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
        raw_name = file_data.get("name", "Untitled")
        mime_type = file_data.get("mimeType", "")
        size = int(file_data.get("size", 0))
        web_view_link = file_data.get("webViewLink", "")
        thumbnail_link = file_data.get("thumbnailLink")
        asset_name = self._asset_display_name(raw_name, mime_type)

        # Check if asset already exists
        stmt = select(Asset).where(Asset.drive_file_id == file_id)
        existing = self.db.scalar(stmt)

        if existing:
            # Update metadata
            existing.name = asset_name
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
                name=raw_name,
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
        asset_name = self._asset_display_name(name, mime_type)

        asset = Asset(
            name=asset_name,
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
        logger.info("Created asset from Drive: %s (%s)", asset_name, file_id)
        return asset

    @staticmethod
    def _asset_display_name(name: str, mime_type: str) -> str:
        if not name:
            return "Untitled"
        suffix = Path(name).suffix
        if not suffix:
            return name
        return Path(name).stem

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
