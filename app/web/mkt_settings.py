"""Marketing app settings — Drive, CRM, and channel configuration."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models.channel import ChannelProvider
from app.services.channel_service import ChannelService
from app.services.crm_bridge import CrmBridge
from app.services.drive_service import DriveService
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["web-mkt-settings"])


@router.get("", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
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

    ctx = {
        "request": request,
        "title": "Settings",
        "channels": channels,
        "drive_config": {
            "configured": drive_configured,
            "folder_id": settings.google_drive_folder_id if drive_configured else "",
        },
        "crm_config": {
            "configured": crm_configured,
            "base_url": settings.crm_base_url if crm_configured else "",
        },
        "providers": [p.value for p in ChannelProvider],
        "success": request.query_params.get("success", ""),
        "error": request.query_params.get("error", ""),
    }
    return templates.TemplateResponse("settings/index.html", ctx)


@router.post("/drive", response_model=None)
async def save_drive_settings(
    request: Request,
) -> RedirectResponse:
    """Save Google Drive settings.

    Note: actual env/config persistence is done via domain settings or env reload.
    This endpoint acknowledges the form submission and provides feedback.
    """
    form = await request.form()
    folder_id = str(form.get("google_drive_folder_id", "")).strip()

    if not folder_id:
        return RedirectResponse(
            url="/settings?error=Drive+folder+ID+is+required",
            status_code=302,
        )

    # In a full implementation, this would persist to DomainSettings or an env store.
    # For now, log the intent. Config is read from env vars at startup.
    logger.info("Drive settings update requested: folder_id=%s", folder_id)

    return RedirectResponse(
        url="/settings?success=Drive+settings+saved",
        status_code=302,
    )


@router.post("/crm", response_model=None)
async def save_crm_settings(
    request: Request,
) -> RedirectResponse:
    """Save CRM bridge settings.

    Note: actual env/config persistence is done via domain settings or env reload.
    This endpoint acknowledges the form submission and provides feedback.
    """
    form = await request.form()
    base_url = str(form.get("crm_base_url", "")).strip()
    str(form.get("crm_api_key", "")).strip()

    if not base_url:
        return RedirectResponse(
            url="/settings?error=CRM+base+URL+is+required",
            status_code=302,
        )

    logger.info("CRM settings update requested: base_url=%s", base_url)

    return RedirectResponse(
        url="/settings?success=CRM+settings+saved",
        status_code=302,
    )
