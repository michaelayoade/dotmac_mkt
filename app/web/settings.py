"""Admin web routes for Domain Settings management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.domain_settings import DomainSetting, SettingDomain
from app.services.branding_context import load_branding_context
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/settings", tags=["web-settings"])


def _base_context(
    request: Request,
    db: Session,
    auth: dict,
    *,
    title: str,
    page_title: str,
) -> dict:
    branding = load_branding_context(db)
    person = auth["person"]
    return {
        "request": request,
        "title": title,
        "page_title": page_title,
        "current_user": person,
        "brand": branding["brand"],
        "org_branding": branding["org_branding"],
        "brand_mark": branding["brand"].get("mark", "A"),
    }


@router.get("", response_class=HTMLResponse)
def list_settings(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List all settings grouped by domain."""
    all_settings = list(
        db.scalars(
            select(DomainSetting)
            .where(DomainSetting.is_active.is_(True))
            .order_by(DomainSetting.domain, DomainSetting.key)
        ).all()
    )

    # Group settings by domain
    grouped: dict[str, list[DomainSetting]] = {}
    for domain in SettingDomain:
        grouped[domain.value] = []
    for setting in all_settings:
        grouped[setting.domain.value].append(setting)

    ctx = _base_context(request, db, auth, title="Settings", page_title="Settings")
    ctx.update(
        {
            "grouped_settings": grouped,
            "domains": [d.value for d in SettingDomain],
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/settings/list.html", ctx)


@router.get("/{setting_id}/edit", response_model=None)
def edit_setting_form(
    request: Request,
    setting_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse | RedirectResponse:
    """Render the edit setting form."""
    setting = db.get(DomainSetting, setting_id)
    if not setting:
        return RedirectResponse(
            url="/admin/settings?error=Setting+not+found",
            status_code=302,
        )

    ctx = _base_context(
        request, db, auth, title="Edit Setting", page_title="Edit Setting"
    )
    ctx["setting"] = setting
    return templates.TemplateResponse("admin/settings/edit.html", ctx)


@router.post("/{setting_id}/edit", response_model=None)
async def edit_setting_submit(
    request: Request,
    setting_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle setting edit form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    setting = db.get(DomainSetting, setting_id)
    if not setting:
        return RedirectResponse(
            url="/admin/settings?error=Setting+not+found",
            status_code=302,
        )

    try:
        # Update value fields based on what was submitted
        value_text_raw = data.get("value_text")
        value_json_raw = data.get("value_json")

        if value_text_raw is not None:
            value_text = str(value_text_raw)
            setting.value_text = value_text if value_text else None
        if value_json_raw is not None:
            value_json_str = str(value_json_raw).strip()
            if value_json_str:
                import json

                setting.value_json = json.loads(value_json_str)

        if "is_active" in data:
            setting.is_active = data["is_active"] == "on"

        db.commit()
        db.refresh(setting)
        logger.info("Updated setting via web: %s/%s", setting.domain.value, setting.key)
        return RedirectResponse(
            url="/admin/settings?success=Setting+updated+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to update setting %s: %s", setting_id, exc)
        db.rollback()
        ctx = _base_context(
            request, db, auth, title="Edit Setting", page_title="Edit Setting"
        )
        ctx["setting"] = setting
        ctx["error"] = str(exc)
        return templates.TemplateResponse("admin/settings/edit.html", ctx)
