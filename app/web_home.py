from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.services import person as person_service
from app.services.branding import save_branding
from app.services.branding_assets import delete_branding_asset, save_branding_asset
from app.services.branding_context import (
    branding_context_from_values,
    load_branding_context,
)
from app.templates import templates

router = APIRouter()


@router.get("/", tags=["web"], response_class=HTMLResponse)
def home(
    request: Request,
    sort: str = "created_at",
    dir: str = "desc",
    page: int = 1,
    db: Session = Depends(get_db),
):
    page = max(page, 1)
    order_by = sort if sort in {"created_at", "last_name", "email"} else "created_at"
    order_dir = dir if dir in {"asc", "desc"} else "desc"
    limit = 25
    offset = (page - 1) * limit

    people = person_service.people.list(
        db=db,
        email=None,
        status=None,
        is_active=None,
        order_by=order_by,
        order_dir=order_dir,
        limit=limit,
        offset=offset,
    )
    total_people = db.query(person_service.Person).count()
    total_pages = max(1, (total_people + limit - 1) // limit)

    branding_ctx = load_branding_context(db)
    brand_name = settings.brand_name
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": brand_name,
            "people": people,
            "brand": branding_ctx["brand"],
            "org_branding": branding_ctx["org_branding"],
            "sort": order_by,
            "dir": order_dir,
            "page": page,
            "total_pages": total_pages,
            "total_people": total_people,
        },
    )


@router.get("/settings/branding", tags=["web"], response_class=HTMLResponse)
def branding_settings(request: Request, db: Session = Depends(get_db)):
    branding_ctx = load_branding_context(db)
    return templates.TemplateResponse(
        "branding.html",
        {
            "request": request,
            "title": "Branding Settings",
            "branding": branding_ctx["branding"],
            "brand": branding_ctx["brand"],
            "org_branding": branding_ctx["org_branding"],
        },
    )


@router.post("/settings/branding", tags=["web"], response_class=HTMLResponse)
async def branding_settings_update(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = dict(form)
    branding_ctx = load_branding_context(db)
    branding = branding_ctx["branding"]

    logo_file = form.get("logo_file")
    logo_dark_file = form.get("logo_dark_file")
    if getattr(logo_file, "filename", None):
        new_logo = await save_branding_asset(logo_file, "logo")
        old_logo = branding.get("logo_url")
        data["logo_url"] = new_logo
        if old_logo and old_logo != new_logo:
            delete_branding_asset(old_logo)
    elif str(form.get("remove_logo") or "").lower() in {"1", "true", "on", "yes"}:
        delete_branding_asset(branding.get("logo_url"))
        data["logo_url"] = None

    if getattr(logo_dark_file, "filename", None):
        new_logo_dark = await save_branding_asset(logo_dark_file, "logo_dark")
        old_logo_dark = branding.get("logo_dark_url")
        data["logo_dark_url"] = new_logo_dark
        if old_logo_dark and old_logo_dark != new_logo_dark:
            delete_branding_asset(old_logo_dark)
    elif str(form.get("remove_logo_dark") or "").lower() in {
        "1",
        "true",
        "on",
        "yes",
    }:
        delete_branding_asset(branding.get("logo_dark_url"))
        data["logo_dark_url"] = None

    payload = {
        "display_name": data.get("display_name"),
        "tagline": data.get("tagline"),
        "brand_mark": data.get("brand_mark"),
        "primary_color": data.get("primary_color"),
        "accent_color": data.get("accent_color"),
        "font_family_display": data.get("font_family_display"),
        "font_family_body": data.get("font_family_body"),
        "custom_css": data.get("custom_css"),
        "logo_url": data.get("logo_url", branding.get("logo_url")),
        "logo_dark_url": data.get("logo_dark_url", branding.get("logo_dark_url")),
    }
    saved = save_branding(db, payload)
    saved_ctx = branding_context_from_values(saved)
    return templates.TemplateResponse(
        "branding.html",
        {
            "request": request,
            "title": "Branding Settings",
            "branding": saved,
            "brand": saved_ctx["brand"],
            "success": True,
            "org_branding": saved_ctx["org_branding"],
        },
    )
