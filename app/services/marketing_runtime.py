from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.services.domain_settings import marketing_settings
from app.services.secrets import resolve_secret

logger = logging.getLogger(__name__)

_ENV_FALLBACKS: dict[str, str] = {
    "meta_graph_version": "v19.0",
    "meta_webhook_verify_token": "",
    "meta_api_timeout_seconds": "30",
}


def _settings_fallback(key: str) -> str:
    direct_values = {
        "encryption_key": settings.encryption_key,
        "meta_app_id": settings.meta_app_id,
        "meta_app_secret": settings.meta_app_secret,
        "twitter_client_id": settings.twitter_client_id,
        "twitter_client_secret": settings.twitter_client_secret,
        "linkedin_client_id": settings.linkedin_client_id,
        "linkedin_client_secret": settings.linkedin_client_secret,
        "google_ads_client_id": settings.google_ads_client_id,
        "google_ads_client_secret": settings.google_ads_client_secret,
        "google_ads_developer_token": settings.google_ads_developer_token,
        "google_analytics_client_id": settings.google_analytics_client_id,
        "google_analytics_client_secret": settings.google_analytics_client_secret,
        "google_drive_client_id": settings.google_drive_client_id,
        "google_drive_client_secret": settings.google_drive_client_secret,
        "google_drive_folder_id": settings.google_drive_folder_id,
        "crm_base_url": settings.crm_base_url,
        "crm_api_key": settings.crm_api_key,
    }
    if key == "google_client_id":
        return (
            settings.google_ads_client_id
            or settings.google_analytics_client_id
            or settings.google_drive_client_id
        )
    if key == "google_client_secret":
        return (
            settings.google_ads_client_secret
            or settings.google_analytics_client_secret
            or settings.google_drive_client_secret
        )
    return direct_values.get(key, "")


def _read_raw(db: Session, key: str) -> str:
    try:
        setting = marketing_settings.get_by_key(db, key)
    except Exception:
        return ""
    return setting.value_text or ""


def _with_session(fn: Callable[[Session], str]) -> str:
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


def get_marketing_value(key: str, db: Session | None = None) -> str:
    aliases = {
        "google_ads_client_id": ("google_client_id",),
        "google_ads_client_secret": ("google_client_secret",),
        "google_analytics_client_id": ("google_client_id",),
        "google_analytics_client_secret": ("google_client_secret",),
        "google_drive_client_id": ("google_client_id",),
        "google_drive_client_secret": ("google_client_secret",),
    }

    def _load(active_db: Session) -> str:
        candidate_keys = (key, *aliases.get(key, ()))
        for candidate_key in candidate_keys:
            raw = _read_raw(active_db, candidate_key)
            if raw:
                return resolve_secret(raw) or ""
        for candidate_key in candidate_keys:
            fallback = _settings_fallback(candidate_key) or _ENV_FALLBACKS.get(
                candidate_key, ""
            )
            if fallback:
                return fallback
        return ""

    if db is not None:
        return _load(db)
    return _with_session(_load)


def get_marketing_int(key: str, default: int, db: Session | None = None) -> int:
    raw = get_marketing_value(key, db)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer marketing setting for %s: %s", key, raw)
        return default
