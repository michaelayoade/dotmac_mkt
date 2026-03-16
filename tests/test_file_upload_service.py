"""Tests for file upload service."""

import shutil
from pathlib import Path

import pytest

from app.models.file_upload import FileUploadStatus
from app.services.file_upload import FileUploadService
from app.services.storage import LocalStorage


@pytest.fixture()
def storage_dir(tmp_path):
    d = tmp_path / "uploads"
    d.mkdir()
    yield str(d)
    if d.exists():
        shutil.rmtree(d)


@pytest.fixture()
def local_storage(storage_dir):
    return LocalStorage(base_dir=storage_dir, url_prefix="/static/uploads")


@pytest.fixture()
def upload_service(db_session, local_storage):
    return FileUploadService(db_session, storage=local_storage)


class TestFileUploadService:
    def test_upload_creates_record(self, upload_service, db_session):
        record = upload_service.upload(
            content=b"test file content",
            filename="test.txt",
            content_type="text/plain",
        )
        assert record.id is not None
        assert record.original_filename == "test.txt"
        assert record.content_type == "text/plain"
        assert record.file_size == len(b"test file content")
        assert record.status == FileUploadStatus.active
        assert record.url is not None

    def test_upload_stores_file(self, upload_service, storage_dir):
        record = upload_service.upload(
            content=b"stored content",
            filename="stored.txt",
            content_type="text/plain",
        )
        assert (Path(storage_dir) / record.storage_key).exists()

    def test_upload_invalid_content_type_raises(self, upload_service):
        with pytest.raises(ValueError, match="not allowed"):
            upload_service.upload(
                content=b"data",
                filename="test.exe",
                content_type="application/x-executable",
            )

    def test_upload_too_large_raises(self, upload_service):
        # Create content larger than max (10MB default in test settings)
        large_content = b"x" * (11 * 1024 * 1024)
        with pytest.raises(ValueError, match="too large"):
            upload_service.upload(
                content=large_content,
                filename="big.txt",
                content_type="text/plain",
            )

    def test_get_by_id(self, upload_service, db_session):
        record = upload_service.upload(
            content=b"data",
            filename="find.txt",
            content_type="text/plain",
        )
        db_session.commit()
        found = upload_service.get_by_id(record.id)
        assert found is not None
        assert found.id == record.id

    def test_get_by_id_not_found(self, upload_service):
        import uuid

        result = upload_service.get_by_id(uuid.uuid4())
        assert result is None

    def test_list_uploads(self, upload_service, db_session):
        upload_service.upload(b"one", "one.txt", "text/plain", category="document")
        upload_service.upload(b"two", "two.txt", "text/plain", category="avatar")
        db_session.commit()

        all_items = upload_service.list_uploads()
        assert len(all_items) >= 2

        docs = upload_service.list_uploads(category="document")
        avatars = upload_service.list_uploads(category="avatar")
        assert all(f.category == "document" for f in docs)
        assert all(f.category == "avatar" for f in avatars)

    def test_delete_soft_deletes(self, upload_service, db_session, storage_dir):
        record = upload_service.upload(
            content=b"delete me",
            filename="delete.txt",
            content_type="text/plain",
        )
        db_session.commit()
        file_id = record.id

        upload_service.delete(file_id)
        db_session.commit()

        found = upload_service.get_by_id(file_id)
        assert found is not None
        assert found.status == FileUploadStatus.deleted
        assert found.is_active is False

    def test_delete_not_found_raises(self, upload_service):
        import uuid

        with pytest.raises(ValueError, match="not found"):
            upload_service.delete(uuid.uuid4())

    def test_upload_with_metadata(self, upload_service, db_session):
        record = upload_service.upload(
            content=b"meta",
            filename="meta.txt",
            content_type="text/plain",
            category="document",
            entity_type="person",
            entity_id="123",
            metadata_={"description": "test file"},
        )
        db_session.commit()
        assert record.entity_type == "person"
        assert record.entity_id == "123"
        assert record.metadata_ == {"description": "test file"}

    def test_count(self, upload_service, db_session):
        initial = upload_service.count()
        upload_service.upload(b"one", "a.csv", "text/csv")
        upload_service.upload(b"two", "b.csv", "text/csv")
        db_session.commit()
        assert upload_service.count() == initial + 2
