"""Marketing app settings — Drive, CRM, and channel configuration."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models.channel import ChannelProvider
from app.models.domain_settings import SettingValueType
from app.schemas.settings import DomainSettingUpdate
from app.services.channel_service import ChannelService
from app.services.crm_bridge import CrmBridge
from app.services.domain_settings import marketing_settings
from app.services.drive_service import DriveService
from app.services.secrets import resolve_secret
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["web-mkt-settings"])


@router.get("", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Settings overview — Drive, CRM, and channel configurations."""
    channel_svc = ChannelService(db)
    channels = channel_svc.list_all()

    drive_configured = DriveService.is_configured()
    crm_bridge = CrmBridge(
        base_url=settings.crm_base_url,
        api_key=settings.crm_api_key,
    )
    crm_configured = crm_bridge.is_configured()

    # Read persisted settings (fall back to env vars)
    drive_folder_id = settings.google_drive_folder_id
    crm_base_url = settings.crm_base_url
    meta_app_id = ""
    meta_app_secret = ""
    meta_graph_version = "v19.0"
    meta_webhook_verify_token = ""
    meta_api_timeout_seconds = "30"
    try:
        drive_setting = marketing_settings.get_by_key(db, "google_drive_folder_id")
        if drive_setting and drive_setting.value_text:
            drive_folder_id = drive_setting.value_text
    except Exception:
        logger.debug("Failed to load google_drive_folder_id setting")
    try:
        crm_setting = marketing_settings.get_by_key(db, "crm_base_url")
        if crm_setting and crm_setting.value_text:
            crm_base_url = crm_setting.value_text
    except Exception:
        logger.debug("Failed to load crm_base_url setting")
    try:
        meta_id_setting = marketing_settings.get_by_key(db, "meta_app_id")
        if meta_id_setting and meta_id_setting.value_text:
            meta_app_id = resolve_secret(meta_id_setting.value_text) or ""
    except Exception:
        logger.debug("Failed to load meta_app_id setting")
    try:
        meta_secret_setting = marketing_settings.get_by_key(db, "meta_app_secret")
        if meta_secret_setting and meta_secret_setting.value_text:
            meta_app_secret = resolve_secret(meta_secret_setting.value_text) or ""
    except Exception:
        logger.debug("Failed to load meta_app_secret setting")
    try:
        setting = marketing_settings.get_by_key(db, "meta_graph_version")
        if setting and setting.value_text:
            meta_graph_version = setting.value_text
    except Exception:
        logger.debug("Failed to load meta_graph_version setting")
    try:
        setting = marketing_settings.get_by_key(db, "meta_webhook_verify_token")
        if setting and setting.value_text:
            meta_webhook_verify_token = resolve_secret(setting.value_text) or ""
    except Exception:
        logger.debug("Failed to load meta_webhook_verify_token setting")
    try:
        setting = marketing_settings.get_by_key(db, "meta_api_timeout_seconds")
        if setting and setting.value_text:
            meta_api_timeout_seconds = setting.value_text
    except Exception:
        logger.debug("Failed to load meta_api_timeout_seconds setting")

    ctx = {
        "request": request,
        "title": "Settings",
        "channels": channels,
        "drive_config": {
            "configured": drive_configured or bool(drive_folder_id),
            "folder_id": drive_folder_id,
        },
        "crm_config": {
            "configured": crm_configured or bool(crm_base_url),
            "base_url": crm_base_url,
        },
        "meta_config": {
            "configured": bool(meta_app_id and meta_app_secret),
            "app_id": meta_app_id,
            "has_secret": bool(meta_app_secret),
            "oauth_redirect_uri": str(request.url_for("meta_callback")),
            "graph_version": meta_graph_version,
            "has_webhook_verify_token": bool(meta_webhook_verify_token),
            "webhook_callback_url": str(request.url_for("meta_webhook")),
            "api_timeout_seconds": meta_api_timeout_seconds,
        },
        "providers": [p.value for p in ChannelProvider],
        "success": request.query_params.get("success", ""),
        "error": request.query_params.get("error", ""),
    }
    return templates.TemplateResponse("settings/index.html", ctx)


@router.post("/drive", response_model=None)
async def save_drive_settings(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Save Google Drive folder ID to domain settings."""
    form = await request.form()
    folder_id = str(form.get("google_drive_folder_id", "")).strip()

    if not folder_id:
        return RedirectResponse(
            url="/settings?error=Drive+folder+ID+is+required",
            status_code=302,
        )

    payload = DomainSettingUpdate(
        value_type=SettingValueType.string,
        value_text=folder_id,
    )
    marketing_settings.upsert_by_key(db, "google_drive_folder_id", payload)
    logger.info("Drive settings saved: folder_id=%s", folder_id)

    return RedirectResponse(
        url="/settings?success=Drive+settings+saved",
        status_code=302,
    )


@router.post("/crm", response_model=None)
async def save_crm_settings(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Save CRM bridge settings to domain settings."""
    form = await request.form()
    base_url = str(form.get("crm_base_url", "")).strip()
    api_key = str(form.get("crm_api_key", "")).strip()

    if not base_url:
        return RedirectResponse(
            url="/settings?error=CRM+base+URL+is+required",
            status_code=302,
        )

    url_payload = DomainSettingUpdate(
        value_type=SettingValueType.string,
        value_text=base_url,
    )
    marketing_settings.upsert_by_key(db, "crm_base_url", url_payload)

    if api_key:
        key_payload = DomainSettingUpdate(
            value_type=SettingValueType.string,
            value_text=api_key,
            is_secret=True,
        )
        marketing_settings.upsert_by_key(db, "crm_api_key", key_payload)

    logger.info("CRM settings saved: base_url=%s", base_url)

    return RedirectResponse(
        url="/settings?success=CRM+settings+saved",
        status_code=302,
    )


@router.post("/meta", response_model=None)
async def save_meta_settings(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    form = await request.form()
    app_id = str(form.get("meta_app_id", "")).strip()
    app_secret = str(form.get("meta_app_secret", "")).strip()
    graph_version = str(form.get("meta_graph_version", "")).strip() or "v19.0"
    webhook_verify_token = str(form.get("meta_webhook_verify_token", "")).strip()
    api_timeout_seconds = str(form.get("meta_api_timeout_seconds", "")).strip() or "30"

    if not app_id:
        return RedirectResponse(
            url="/settings?error=Meta+App+ID+is+required",
            status_code=302,
        )
    if not app_secret:
        return RedirectResponse(
            url="/settings?error=Meta+App+Secret+is+required",
            status_code=302,
        )

    marketing_settings.upsert_by_key(
        db,
        "meta_app_id",
        DomainSettingUpdate(
            value_type=SettingValueType.string,
            value_text=app_id,
        ),
    )
    marketing_settings.upsert_by_key(
        db,
        "meta_app_secret",
        DomainSettingUpdate(
            value_type=SettingValueType.string,
            value_text=app_secret,
            is_secret=True,
        ),
    )
    marketing_settings.upsert_by_key(
        db,
        "meta_graph_version",
        DomainSettingUpdate(
            value_type=SettingValueType.string,
            value_text=graph_version,
        ),
    )
    marketing_settings.upsert_by_key(
        db,
        "meta_webhook_verify_token",
        DomainSettingUpdate(
            value_type=SettingValueType.string,
            value_text=webhook_verify_token,
            is_secret=True,
        ),
    )
    marketing_settings.upsert_by_key(
        db,
        "meta_api_timeout_seconds",
        DomainSettingUpdate(
            value_type=SettingValueType.integer,
            value_text=api_timeout_seconds,
        ),
    )
    logger.info("Meta app settings saved")

    return RedirectResponse(
        url="/settings?success=Meta+settings+saved",
        status_code=302,
    )
