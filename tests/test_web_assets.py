from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from jose import jwt

from app.models.asset import Asset, AssetType
from app.services.auth_flow import hash_session_token


def test_create_asset_uploads_file_to_drive_via_service(
    client, db_session, auth_token, person, monkeypatch
):
    created: dict[str, bytes | str] = {}

    def _fake_upload_asset_file(
        self,
        *,
        filename: str,
        drive_filename: str | None = None,
        folder_id: str | None = None,
        content_type: str,
        content: bytes,
        uploaded_by=None,
    ):
        created["filename"] = filename
        created["drive_filename"] = drive_filename or ""
        created["folder_id"] = folder_id or ""
        created["content_type"] = content_type
        created["content"] = content
        asset = Asset(
            name=drive_filename or filename,
            asset_type=AssetType.image,
            drive_file_id="drive-file-999",
            drive_url="https://drive.google.com/file/d/drive-file-999/view",
            mime_type=content_type,
            file_size=len(content),
            tags=[],
            uploaded_by=uploaded_by,
        )
        db_session.add(asset)
        db_session.flush()
        return asset

    monkeypatch.setattr(
        "app.web.assets.DriveService.upload_asset_file",
        _fake_upload_asset_file,
    )
    monkeypatch.setattr(
        "app.web.assets.DriveService.get_folder",
        lambda self, *, folder_id: (
            {"id": folder_id, "name": "Marketing Resources"} if folder_id else None
        ),
    )

    resp = client.get("/assets/create", cookies={"access_token": auth_token})
    csrf_token = resp.cookies.get("csrf_token", "")
    response = client.post(
        "/assets/create",
        data={
            "name": "Drive Banner",
            "asset_type": "image",
            "tags": "launch,banner",
            "drive_folder_id": "folder-social",
            "csrf_token": csrf_token,
        },
        files={"file": ("banner.png", b"png-bytes", "image/png")},
        cookies={"access_token": auth_token, "csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/assets/")
    assert created["filename"] == "banner.png"
    assert created["drive_filename"] == "Drive Banner"
    assert created["folder_id"] == "folder-social"
    assert created["content_type"] == "image/png"
    assert created["content"] == b"png-bytes"


def test_create_asset_can_link_uploaded_file_to_campaign(
    client, db_session, auth_token, person, campaign, monkeypatch
):
    def _fake_upload_asset_file(
        self,
        *,
        filename: str,
        drive_filename: str | None = None,
        folder_id: str | None = None,
        content_type: str,
        content: bytes,
        uploaded_by=None,
    ):
        asset = Asset(
            name=drive_filename or filename,
            asset_type=AssetType.image,
            drive_file_id="drive-file-campaign",
            drive_url="https://drive.google.com/file/d/drive-file-campaign/view",
            mime_type=content_type,
            file_size=len(content),
            tags=[],
            uploaded_by=uploaded_by,
        )
        db_session.add(asset)
        db_session.flush()
        return asset

    monkeypatch.setattr(
        "app.web.assets.DriveService.upload_asset_file",
        _fake_upload_asset_file,
    )
    monkeypatch.setattr(
        "app.web.assets.DriveService.get_folder",
        lambda self, *, folder_id: (
            {"id": folder_id, "name": "Marketing Resources"} if folder_id else None
        ),
    )

    resp = client.get(
        f"/assets/create?campaign_id={campaign.id}&next=/campaigns/{campaign.id}",
        cookies={"access_token": auth_token},
    )
    csrf_token = resp.cookies.get("csrf_token", "")
    response = client.post(
        "/assets/create",
        data={
            "name": "Campaign Banner",
            "asset_type": "image",
            "campaign_id": str(campaign.id),
            "next": f"/campaigns/{campaign.id}",
            "csrf_token": csrf_token,
        },
        files={"file": ("banner.png", b"png-bytes", "image/png")},
        cookies={"access_token": auth_token, "csrf_token": csrf_token},
        follow_redirects=False,
    )

    db_session.refresh(campaign)

    assert response.status_code == 302
    assert response.headers["location"] == f"/campaigns/{campaign.id}"
    assert any(asset.name == "Campaign Banner" for asset in campaign.assets)


def test_create_asset_form_shows_drive_folder_search(client, auth_token, monkeypatch):
    monkeypatch.setattr(
        "app.web.assets.DriveService.get_folder",
        lambda self, *, folder_id: (
            {"id": folder_id, "name": "Marketing Resources"} if folder_id else None
        ),
    )

    response = client.get(
        "/assets/create",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    html = response.text
    assert "Drive Destination Folder" in html
    assert "Search Google Drive folders..." in html
    assert 'data-typeahead-url="/assets/drive-folders/search"' in html


def test_create_asset_form_refreshes_expired_access_cookie(
    client, db_session, auth_session, person, monkeypatch
):
    refresh_token = "refresh-token-for-assets-form"
    auth_session.token_hash = hash_session_token(refresh_token)
    db_session.commit()

    secret = "test-secret"
    now = datetime.now(UTC)
    expired_access = jwt.encode(
        {
            "sub": str(person.id),
            "session_id": str(auth_session.id),
            "roles": [],
            "scopes": [],
            "typ": "access",
            "exp": int((now - timedelta(minutes=1)).timestamp()),
            "iat": int((now - timedelta(minutes=16)).timestamp()),
        },
        secret,
        algorithm="HS256",
    )

    monkeypatch.setattr(
        "app.web.assets.DriveService.get_folder",
        lambda self, *, folder_id: (
            {"id": folder_id, "name": "Marketing Resources"} if folder_id else None
        ),
    )

    response = client.get(
        "/assets/create",
        cookies={
            "access_token": expired_access,
            "refresh_token": refresh_token,
        },
    )

    assert response.status_code == 200
    assert "Upload Asset" in response.text
    assert response.cookies.get("access_token")
    assert response.cookies.get("refresh_token")


def test_drive_folder_search_returns_matching_items(client, auth_token, monkeypatch):
    monkeypatch.setattr(
        "app.web.assets.DriveService.search_folders",
        lambda self, *, query, limit: [
            {"id": "folder-brand", "name": "Brand Assets"},
            {"id": "folder-social", "name": "Social Content"},
        ],
    )

    response = client.get(
        "/assets/drive-folders/search?q=bra",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["id"] == "folder-brand"
    assert data["items"][0]["label"] == "Brand Assets"


def test_drive_folder_search_shows_default_parent_and_children_on_empty_query(
    client, auth_token, monkeypatch
):
    monkeypatch.setattr(
        "app.web.assets.DriveService.search_folders",
        lambda self, *, query, limit: (
            [
                {"id": "default-folder", "name": "Marketing Resources"},
                {"id": "folder-hd", "name": "HD resources"},
                {"id": "folder-promo", "name": "promotional videos"},
            ]
            if query == ""
            else []
        ),
    )

    response = client.get(
        "/assets/drive-folders/search?q=",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert [item["label"] for item in data["items"]] == [
        "Marketing Resources",
        "HD resources",
        "promotional videos",
    ]


def test_google_ads_oauth_requests_drive_upload_scope(
    client, auth_token, person, auth_session, monkeypatch
):
    import sys

    mock_cfg = sys.modules["app.config"]
    monkeypatch.setattr(mock_cfg.settings, "google_ads_client_id", "client-id")

    response = client.get(
        "/channels/google_ads/connect?external_account_id=1234567890",
        cookies={"access_token": auth_token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    parsed = urlparse(response.headers["location"])
    params = parse_qs(parsed.query)
    scope = params["scope"][0]
    assert "https://www.googleapis.com/auth/adwords" in scope
    assert "https://www.googleapis.com/auth/drive.file" in scope


def test_edit_asset_updates_name_type_tags_and_drive_file_id(
    client, db_session, auth_token, asset, monkeypatch
):
    renamed: dict[str, str] = {}

    def _fake_rename_asset_file(self, *, file_id: str, display_name: str) -> dict:
        renamed["file_id"] = file_id
        renamed["display_name"] = display_name
        return {"id": file_id, "name": f"{display_name}.png", "mimeType": "image/png"}

    monkeypatch.setattr(
        "app.web.assets.DriveService.rename_asset_file",
        _fake_rename_asset_file,
    )

    resp = client.get(
        f"/assets/{asset.id}/edit",
        cookies={"access_token": auth_token},
    )
    csrf_token = resp.cookies.get("csrf_token", "")

    response = client.post(
        f"/assets/{asset.id}/edit",
        data={
            "name": "Updated Drive Asset",
            "asset_type": "template",
            "tags": "hero,q2,launch",
            "drive_file_id": "drive-updated-123",
            "csrf_token": csrf_token,
        },
        cookies={"access_token": auth_token, "csrf_token": csrf_token},
        follow_redirects=False,
    )

    db_session.refresh(asset)

    assert response.status_code == 302
    assert response.headers["location"] == f"/assets/{asset.id}"
    assert asset.name == "Updated Drive Asset"
    assert asset.asset_type == AssetType.template
    assert asset.tags == ["hero", "q2", "launch"]
    assert asset.drive_file_id == "drive-updated-123"
    assert renamed["file_id"] == "abc123"
    assert renamed["display_name"] == "Updated Drive Asset"


def test_delete_asset_removes_drive_file_and_marks_asset_missing(
    client, db_session, auth_token, asset, monkeypatch
):
    deleted: dict[str, str] = {}

    def _fake_delete_asset_file(self, *, file_id: str) -> None:
        deleted["file_id"] = file_id

    monkeypatch.setattr(
        "app.web.assets.DriveService.delete_asset_file",
        _fake_delete_asset_file,
    )

    resp = client.get(
        f"/assets/{asset.id}/edit",
        cookies={"access_token": auth_token},
    )
    csrf_token = resp.cookies.get("csrf_token", "")

    response = client.post(
        f"/assets/{asset.id}/delete",
        data={"csrf_token": csrf_token},
        cookies={"access_token": auth_token, "csrf_token": csrf_token},
        follow_redirects=False,
    )

    db_session.refresh(asset)

    assert response.status_code == 302
    assert response.headers["location"] == "/assets?success=Asset+deleted"
    assert deleted["file_id"] == "abc123"
    assert str(asset.drive_status) == "DriveStatus.missing"


def test_asset_detail_uses_thumbnail_preview_for_images(
    client, auth_token, asset, monkeypatch
):
    monkeypatch.setattr("app.web.assets._refresh_drive_assets", lambda db: None)
    asset.thumbnail_url = "https://thumb.example/asset.png"

    response = client.get(
        f"/assets/{asset.id}",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    assert 'src="https://thumb.example/asset.png"' in response.text
    assert 'src="https://drive.google.com/file/d/abc123"' not in response.text


def test_asset_detail_uses_mime_type_for_preview_when_asset_type_is_not_image(
    client, auth_token, asset, monkeypatch
):
    monkeypatch.setattr("app.web.assets._refresh_drive_assets", lambda db: None)
    asset.asset_type = AssetType.template
    asset.mime_type = "image/png"
    asset.thumbnail_url = None

    response = client.get(
        f"/assets/{asset.id}",
        cookies={"access_token": auth_token},
    )

    assert response.status_code == 200
    assert (
        'src="https://drive.google.com/thumbnail?id=abc123&amp;sz=w1600"'
        in response.text
    )
