"""Storage backend abstraction for file uploads.

Supports local filesystem and S3-compatible storage. The backend is
selected via ``settings.storage_backend`` ("local" or "s3").
"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract interface for file storage."""

    @abstractmethod
    def save(self, content: bytes, filename: str, content_type: str) -> str:
        """Save content and return a storage key."""

    @abstractmethod
    def delete(self, storage_key: str) -> None:
        """Delete a stored file by its key."""

    @abstractmethod
    def get_url(self, storage_key: str) -> str:
        """Return a public URL for the stored file."""

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Check whether a file exists in storage."""


class LocalStorage(StorageBackend):
    """Store files on the local filesystem."""

    def __init__(
        self, base_dir: str | None = None, url_prefix: str | None = None
    ) -> None:
        self.base_dir = Path(base_dir or settings.storage_local_dir)
        self.url_prefix = (url_prefix or settings.storage_url_prefix).rstrip("/")

    def save(self, content: bytes, filename: str, content_type: str) -> str:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        unique = uuid.uuid4().hex[:10]
        ext = Path(filename).suffix or ""
        storage_key = (
            f"{unique}_{filename}" if len(filename) <= 80 else f"{unique}{ext}"
        )
        file_path = self.base_dir / storage_key
        with open(file_path, "wb") as f:
            f.write(content)
        logger.info("Saved file: %s (%d bytes)", storage_key, len(content))
        return storage_key

    def delete(self, storage_key: str) -> None:
        file_path = self._resolve_path(storage_key)
        if file_path and file_path.exists():
            os.remove(file_path)
            logger.info("Deleted file: %s", storage_key)

    def get_url(self, storage_key: str) -> str:
        return f"{self.url_prefix}/{storage_key}"

    def exists(self, storage_key: str) -> bool:
        file_path = self._resolve_path(storage_key)
        return file_path is not None and file_path.exists()

    def _resolve_path(self, storage_key: str) -> Path | None:
        """Resolve and validate a path to prevent directory traversal."""
        base = self.base_dir.resolve()
        target = (base / storage_key).resolve()
        if not str(target).startswith(str(base) + os.sep) and target != base:
            return None
        return target


class S3Storage(StorageBackend):
    """Store files in an S3-compatible bucket.

    boto3 is imported lazily so the dependency is optional for local dev.
    """

    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self.bucket = bucket or settings.s3_bucket
        self.region = region or settings.s3_region
        self._access_key = access_key or settings.s3_access_key
        self._secret_key = secret_key or settings.s3_secret_key
        self._endpoint_url = endpoint_url or settings.s3_endpoint_url
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            import boto3  # type: ignore[import-untyped]

            kwargs: dict[str, str] = {
                "region_name": self.region,
                "aws_access_key_id": self._access_key,
                "aws_secret_access_key": self._secret_key,
            }
            if self._endpoint_url:
                kwargs["endpoint_url"] = self._endpoint_url
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def save(self, content: bytes, filename: str, content_type: str) -> str:
        unique = uuid.uuid4().hex[:10]
        ext = Path(filename).suffix or ""
        storage_key = (
            f"{unique}_{filename}" if len(filename) <= 80 else f"{unique}{ext}"
        )
        client = self._get_client()
        client.put_object(  # type: ignore[union-attr]
            Bucket=self.bucket,
            Key=storage_key,
            Body=content,
            ContentType=content_type,
        )
        logger.info("Saved file to S3: %s (%d bytes)", storage_key, len(content))
        return storage_key

    def delete(self, storage_key: str) -> None:
        client = self._get_client()
        client.delete_object(Bucket=self.bucket, Key=storage_key)  # type: ignore[union-attr]
        logger.info("Deleted file from S3: %s", storage_key)

    def get_url(self, storage_key: str) -> str:
        if self._endpoint_url:
            return f"{self._endpoint_url}/{self.bucket}/{storage_key}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{storage_key}"

    def exists(self, storage_key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=storage_key)  # type: ignore[union-attr]
            return True
        except Exception:
            return False


def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend instance."""
    backend = settings.storage_backend
    if backend == "s3":
        return S3Storage()
    return LocalStorage()
