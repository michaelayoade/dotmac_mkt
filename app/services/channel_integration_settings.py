from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.marketing_runtime import get_marketing_int, get_marketing_value


@dataclass(frozen=True)
class MetaIntegrationConfig:
    app_id: str
    app_secret: str
    graph_version: str
    webhook_verify_token: str
    api_timeout_seconds: int


def get_meta_oauth_config(db: Session) -> MetaIntegrationConfig:
    return MetaIntegrationConfig(
        app_id=get_marketing_value("meta_app_id", db),
        app_secret=get_marketing_value("meta_app_secret", db),
        graph_version=get_marketing_value("meta_graph_version", db) or "v19.0",
        webhook_verify_token=get_marketing_value("meta_webhook_verify_token", db),
        api_timeout_seconds=get_marketing_int("meta_api_timeout_seconds", 30, db),
    )
