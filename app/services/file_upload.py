"""File upload service — CRUD + storage integration."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.file_upload import FileUpload, FileUploadStatus
from app.services.storage import StorageBackend, get_storage_backend

logger = logging.getLogger(__name__)


class FileUploadService:
    """Manages file upload records and storage."""

    def __init__(self, db: Session, storage: StorageBackend | None = None) -> None:
        self.db = db
        self.storage = storage or get_storage_backend()

    def upload(
        self,
        content: bytes,
        filename: str,
        content_type: str,
        uploaded_by: UUID | None = None,
        category: str = "document",
        entity_type: str | None = None,
        entity_id: str | None = None,
        metadata_: dict | None = None,
    ) -> FileUpload:
        """Upload a file and create a database record."""
        allowed = {t.strip() for t in settings.upload_allowed_types.split(",")}
        if content_type not in allowed:
            raise ValueError(f"File type '{content_type}' not allowed")
        if len(content) > settings.upload_max_size_bytes:
            max_mb = settings.upload_max_size_bytes // (1024 * 1024)
            raise ValueError(f"File too large. Maximum size: {max_mb}MB")

        storage_key = self.storage.save(content, filename, content_type)
        url = self.storage.get_url(storage_key)

        record = FileUpload(
            uploaded_by=uploaded_by,
            original_filename=filename,
            content_type=content_type,
            file_size=len(content),
            storage_backend=settings.storage_backend,
            storage_key=storage_key,
            url=url,
            category=category,
            entity_type=entity_type,
            entity_id=entity_id,
            status=FileUploadStatus.active,
            metadata_=metadata_,
        )
        self.db.add(record)
        self.db.flush()
        logger.info("Uploaded file: %s (id=%s)", filename, record.id)
        return record

    def get_by_id(self, file_id: UUID) -> FileUpload | None:
        """Get a file upload by ID."""
        return self.db.get(FileUpload, file_id)

    def list_uploads(
        self,
        *,
        uploaded_by: UUID | None = None,
        category: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FileUpload]:
        """List file uploads with optional filters."""
        stmt = select(FileUpload).where(
            FileUpload.is_active.is_(True),
            FileUpload.status == FileUploadStatus.active,
        )
        if uploaded_by is not None:
            stmt = stmt.where(FileUpload.uploaded_by == uploaded_by)
        if category is not None:
            stmt = stmt.where(FileUpload.category == category)
        if entity_type is not None:
            stmt = stmt.where(FileUpload.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(FileUpload.entity_id == entity_id)
        stmt = stmt.order_by(FileUpload.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def count(
        self,
        *,
        uploaded_by: UUID | None = None,
        category: str | None = None,
    ) -> int:
        """Count active file uploads."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(FileUpload)
            .where(
                FileUpload.is_active.is_(True),
                FileUpload.status == FileUploadStatus.active,
            )
        )
        if uploaded_by is not None:
            stmt = stmt.where(FileUpload.uploaded_by == uploaded_by)
        if category is not None:
            stmt = stmt.where(FileUpload.category == category)
        result = self.db.execute(stmt).scalar()
        return result or 0

    def delete(self, file_id: UUID) -> None:
        """Soft-delete a file upload and remove from storage."""
        record = self.db.get(FileUpload, file_id)
        if not record:
            raise ValueError("File upload not found")
        try:
            self.storage.delete(record.storage_key)
        except Exception:
            logger.exception(
                "Failed to delete file from storage: %s", record.storage_key
            )
        record.status = FileUploadStatus.deleted
        record.is_active = False
        self.db.flush()
        logger.info("Deleted file upload: %s", file_id)
