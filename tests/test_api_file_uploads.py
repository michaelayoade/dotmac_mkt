"""Tests for file upload API endpoints."""

import io
from unittest.mock import MagicMock, patch


def _csrf_headers(client) -> dict[str, str]:
    """Get a valid CSRF token from the test client."""
    # Hit a GET endpoint to get a CSRF cookie set
    resp = client.get("/health")
    token = resp.cookies.get("csrf_token", "")
    return {"X-CSRF-Token": token}


class TestFileUploadAPI:
    def test_upload_file(self, client, auth_headers):
        file_content = b"hello world test file"
        csrf = _csrf_headers(client)
        headers = {**auth_headers, **csrf}
        with patch("app.services.file_upload.get_storage_backend") as mock_backend:
            storage = MagicMock()
            storage.save.return_value = "abc123_test.txt"
            storage.get_url.return_value = "/static/uploads/abc123_test.txt"
            mock_backend.return_value = storage

            response = client.post(
                "/file-uploads",
                files={"file": ("test.txt", io.BytesIO(file_content), "text/plain")},
                data={
                    "category": "document",
                    "csrf_token": csrf.get("X-CSRF-Token", ""),
                },
                headers=headers,
                cookies=client.cookies,
            )
        assert response.status_code == 201
        data = response.json()
        assert data["original_filename"] == "test.txt"
        assert data["content_type"] == "text/plain"
        assert data["category"] == "document"

    def test_upload_file_unauthenticated(self, client):
        csrf = _csrf_headers(client)
        response = client.post(
            "/file-uploads",
            files={"file": ("test.txt", io.BytesIO(b"data"), "text/plain")},
            data={"csrf_token": csrf.get("X-CSRF-Token", "")},
            headers=csrf,
            cookies=client.cookies,
        )
        assert response.status_code == 401

    def test_list_file_uploads(self, client, auth_headers, db_session):
        from app.models.file_upload import FileUpload, FileUploadStatus

        upload = FileUpload(
            original_filename="existing.txt",
            content_type="text/plain",
            file_size=100,
            storage_key="key123",
            url="/static/uploads/key123",
            status=FileUploadStatus.active,
        )
        db_session.add(upload)
        db_session.commit()

        response = client.get("/file-uploads", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert data["total"] >= 1

    def test_get_file_upload(self, client, auth_headers, db_session):
        from app.models.file_upload import FileUpload, FileUploadStatus

        upload = FileUpload(
            original_filename="get_test.txt",
            content_type="text/plain",
            file_size=50,
            storage_key="getkey",
            url="/static/uploads/getkey",
            status=FileUploadStatus.active,
        )
        db_session.add(upload)
        db_session.commit()
        db_session.refresh(upload)

        response = client.get(f"/file-uploads/{upload.id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["original_filename"] == "get_test.txt"

    def test_get_file_upload_not_found(self, client, auth_headers):
        import uuid

        response = client.get(f"/file-uploads/{uuid.uuid4()}", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_file_upload(self, client, auth_headers, db_session):
        from app.models.file_upload import FileUpload, FileUploadStatus

        upload = FileUpload(
            original_filename="del_test.txt",
            content_type="text/plain",
            file_size=10,
            storage_key="delkey",
            url="/static/uploads/delkey",
            status=FileUploadStatus.active,
        )
        db_session.add(upload)
        db_session.commit()
        db_session.refresh(upload)

        with patch("app.services.file_upload.get_storage_backend") as mock_backend:
            storage = MagicMock()
            mock_backend.return_value = storage

            response = client.delete(f"/file-uploads/{upload.id}", headers=auth_headers)
        assert response.status_code == 204
