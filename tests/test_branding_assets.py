"""Tests for branding asset upload hardening."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.services import branding_assets


@pytest.mark.asyncio
async def test_save_branding_asset_sniffs_png_content(tmp_path: Path) -> None:
    # PNG signature + minimal data
    png = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 32)
    file = MagicMock(spec=UploadFile)
    file.content_type = "image/png"
    file.read = AsyncMock(side_effect=[png, b""])

    with (
        patch.object(
            branding_assets.settings, "branding_upload_dir", str(tmp_path), create=True
        ),
        patch.object(
            branding_assets.settings,
            "branding_url_prefix",
            "/static/branding",
            create=True,
        ),
        patch.object(
            branding_assets.settings,
            "branding_max_size_bytes",
            1024 * 1024,
            create=True,
        ),
        patch.object(
            branding_assets.settings, "branding_allowed_types", "image/png", create=True
        ),
    ):
        url = await branding_assets.save_branding_asset(file, "logo")
    assert url.startswith("/static/branding/logo_")


@pytest.mark.asyncio
async def test_rejects_mismatch_declared_and_sniffed_type(tmp_path: Path) -> None:
    # PNG bytes declared as JPEG should fail.
    png = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 32)
    file = MagicMock(spec=UploadFile)
    file.content_type = "image/jpeg"
    file.read = AsyncMock(side_effect=[png, b""])

    with (
        patch.object(
            branding_assets.settings, "branding_upload_dir", str(tmp_path), create=True
        ),
        patch.object(
            branding_assets.settings,
            "branding_max_size_bytes",
            1024 * 1024,
            create=True,
        ),
        patch.object(
            branding_assets.settings,
            "branding_allowed_types",
            "image/jpeg",
            create=True,
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await branding_assets.save_branding_asset(file, "logo")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_rejects_unsafe_svg(tmp_path: Path) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    file = MagicMock(spec=UploadFile)
    file.content_type = "image/svg+xml"
    file.read = AsyncMock(side_effect=[svg, b""])

    with (
        patch.object(
            branding_assets.settings, "branding_upload_dir", str(tmp_path), create=True
        ),
        patch.object(
            branding_assets.settings,
            "branding_max_size_bytes",
            1024 * 1024,
            create=True,
        ),
        patch.object(
            branding_assets.settings,
            "branding_allowed_types",
            "image/svg+xml",
            create=True,
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await branding_assets.save_branding_asset(file, "logo")
    assert "unsafe svg" in exc.value.detail.lower()


def test_delete_branding_asset_blocks_path_traversal(tmp_path: Path) -> None:
    keep = tmp_path / "keep.txt"
    keep.write_text("do-not-delete", encoding="utf-8")

    with (
        patch.object(
            branding_assets.settings, "branding_upload_dir", str(tmp_path), create=True
        ),
        patch.object(
            branding_assets.settings,
            "branding_url_prefix",
            "/static/branding",
            create=True,
        ),
    ):
        branding_assets.delete_branding_asset("/static/branding/../../keep.txt")

    assert keep.exists()
