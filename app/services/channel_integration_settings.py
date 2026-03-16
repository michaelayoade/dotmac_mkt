from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.domain_settings import marketing_settings
from app.services.secrets import resolve_secret


def _marketing_value(db: Session, key: str) -> str:
    try:
        setting = marketing_settings.get_by_key(db, key)
    except Exception:
        return ""
    value = setting.value_text or ""
    return resolve_secret(value) or ""


def _marketing_int(db: Session, key: str, default: int) -> int:
    raw = _marketing_value(db, key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class MetaIntegrationConfig:
    app_id: str
    app_secret: str
    graph_version: str
    webhook_verify_token: str
    api_timeout_seconds: int


def get_meta_oauth_config(db: Session) -> MetaIntegrationConfig:
    return MetaIntegrationConfig(
        app_id=_marketing_value(db, "meta_app_id"),
        app_secret=_marketing_value(db, "meta_app_secret"),
        graph_version=_marketing_value(db, "meta_graph_version") or "v19.0",
        webhook_verify_token=_marketing_value(db, "meta_webhook_verify_token"),
        api_timeout_seconds=_marketing_int(db, "meta_api_timeout_seconds", 30),
    )
