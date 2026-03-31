from __future__ import annotations

import pytest

from app.models.asset import AssetType
from app.services.drive_service import DriveService


class _FakeDriveCreateCall:
    def execute(self) -> dict:
        return {
            "id": "drive-file-123",
            "name": "banner.png",
            "mimeType": "image/png",
            "size": "128",
            "webViewLink": "https://drive.google.com/file/d/drive-file-123/view",
            "thumbnailLink": "https://thumb.example/banner.png",
        }


class _FakeDriveFiles:
    def create(self, **kwargs) -> _FakeDriveCreateCall:
        return _FakeDriveCreateCall()


class _FakeDriveApi:
    def files(self) -> _FakeDriveFiles:
        return _FakeDriveFiles()


def test_upload_asset_file_creates_local_asset_record(db_session, person, monkeypatch):
    service = DriveService(db_session)
    monkeypatch.setattr(
        service,
        "_drive_client_config",
        lambda: ("client-id", "client-secret", "folder-123"),
    )
    monkeypatch.setattr(
        service,
        "_token_data",
        lambda: {
            "scope": "https://www.googleapis.com/auth/drive.file",
            "access_token": "token",
            "refresh_token": "refresh",
        },
    )
    monkeypatch.setattr(service, "_build_drive_service", lambda: _FakeDriveApi())

    asset = service.upload_asset_file(
        filename="banner.png",
        drive_filename="Homepage Hero",
        content_type="image/png",
        content=b"\x89PNG\r\n\x1a\n" + (b"\x00" * 120),
        uploaded_by=person.id,
    )
    db_session.commit()

    assert asset.drive_file_id == "drive-file-123"
    assert asset.name == "Homepage Hero"
    assert asset.asset_type == AssetType.image
    assert asset.file_size == 128
    assert asset.uploaded_by == person.id


def test_upload_asset_file_rejects_missing_drive_write_scope(db_session, monkeypatch):
    service = DriveService(db_session)
    monkeypatch.setattr(
        service,
        "_drive_client_config",
        lambda: ("client-id", "client-secret", "folder-123"),
    )
    monkeypatch.setattr(
        service,
        "_token_data",
        lambda: {
            "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
        },
    )

    with pytest.raises(RuntimeError) as exc:
        service.upload_asset_file(
            filename="banner.png",
            drive_filename="Homepage Hero",
            content_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + (b"\x00" * 64),
        )

    assert "drive.file" in str(exc.value)
