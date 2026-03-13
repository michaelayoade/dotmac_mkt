import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import settings


def get_allowed_types() -> set[str]:
    return {
        item.strip()
        for item in settings.avatar_allowed_types.split(",")
        if item.strip()
    }


def _sniff_content_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_avatar(file: UploadFile, sniffed_type: str | None) -> str:
    allowed_types = get_allowed_types()
    declared_type = file.content_type or ""

    if declared_type and declared_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(sorted(allowed_types))}",
        )
    if not sniffed_type:
        raise HTTPException(
            status_code=400,
            detail="Could not verify uploaded file type",
        )
    if sniffed_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Detected file type is not allowed",
        )
    if declared_type and declared_type != sniffed_type:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file content does not match file type",
        )
    return sniffed_type


async def save_avatar(file: UploadFile, person_id: str) -> str:
    head = await file.read(512)
    sniffed_type = _sniff_content_type(head)
    content_type = validate_avatar(file, sniffed_type)

    upload_dir = Path(settings.avatar_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = _get_extension(content_type)
    filename = f"{person_id}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = upload_dir / filename

    content = head + await file.read()
    if len(content) > settings.avatar_max_size_bytes:
        max_size_mb = settings.avatar_max_size_bytes // 1024 // 1024
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {max_size_mb}MB",
        )

    with open(file_path, "wb") as f:
        f.write(content)

    return f"{settings.avatar_url_prefix}/{filename}"


def delete_avatar(avatar_url: str | None) -> None:
    if not avatar_url:
        return

    if avatar_url.startswith(settings.avatar_url_prefix):
        filename = avatar_url.replace(settings.avatar_url_prefix + "/", "")
        file_path = Path(settings.avatar_upload_dir) / filename
        if file_path.exists():
            os.remove(file_path)


def _get_extension(content_type: str) -> str:
    extensions = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    return extensions.get(content_type, ".jpg")
