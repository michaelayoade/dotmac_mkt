from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.services.branding import generate_css, get_branding, google_fonts_url


def _brand_mark(name: str) -> str:
    parts = [part for part in name.split() if part]
    if not parts:
        return "ST"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def branding_context_from_values(branding: dict[str, Any]) -> dict[str, Any]:
    brand_name = settings.brand_name
    return {
        "branding": branding,
        "brand": {
            "name": branding.get("display_name") or brand_name,
            "tagline": branding.get("tagline") or settings.brand_tagline,
            "logo_url": branding.get("logo_url") or settings.brand_logo_url,
            "logo_dark_url": branding.get("logo_dark_url"),
            "mark": branding.get("brand_mark") or _brand_mark(brand_name),
        },
        "org_branding": {
            "css": generate_css(branding),
            "fonts_url": google_fonts_url(branding),
        },
    }


def load_branding_context(db: Session) -> dict[str, Any]:
    return branding_context_from_values(get_branding(db))
