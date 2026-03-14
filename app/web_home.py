import re

from fastapi import APIRouter, Depends, Request, status
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
NEWSLETTER_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _canonical_url(request: Request) -> str:
    canonical_host = (settings.canonical_host or "").strip()
    canonical_scheme = (settings.canonical_scheme or request.url.scheme).strip()
    if canonical_host:
        return str(
            request.url.replace(
                scheme=canonical_scheme,
                netloc=canonical_host,
            )
        )
    return str(request.url)


def _render_home_page(
    request: Request,
    db: Session,
    current_page: str,
    newsletter_email: str = "",
    newsletter_error: str | None = None,
    newsletter_success: str | None = None,
    response_status: int = status.HTTP_200_OK,
):
    page = 1
    order_by = "created_at"
    order_dir = "desc"
    limit = 25
    offset = 0

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
            "current_page": current_page,
            "canonical_url": _canonical_url(request),
            "newsletter_email": newsletter_email,
            "newsletter_error": newsletter_error,
            "newsletter_success": newsletter_success,
        },
        status_code=response_status,
    )


@router.get("/", tags=["web"], response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    return _render_home_page(request=request, db=db, current_page="home")


@router.get("/services", tags=["web"], response_class=HTMLResponse)
def services_page(request: Request, db: Session = Depends(get_db)):
    return _render_home_page(request=request, db=db, current_page="services")


@router.get("/plans", tags=["web"], response_class=HTMLResponse)
def plans_page(request: Request, db: Session = Depends(get_db)):
    return _render_home_page(request=request, db=db, current_page="plans")


@router.get("/contact", tags=["web"], response_class=HTMLResponse)
def contact_page(request: Request, db: Session = Depends(get_db)):
    return _render_home_page(request=request, db=db, current_page="contact")


@router.post("/contact/newsletter", tags=["web"], response_class=HTMLResponse)
async def contact_newsletter(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    email = str(form.get("newsletter_email") or "").strip()
    if not email:
        return _render_home_page(
            request=request,
            db=db,
            current_page="contact",
            newsletter_email=email,
            newsletter_error="Enter an email address to join the newsletter.",
            response_status=status.HTTP_400_BAD_REQUEST,
        )
    if not NEWSLETTER_EMAIL_RE.match(email):
        return _render_home_page(
            request=request,
            db=db,
            current_page="contact",
            newsletter_email=email,
            newsletter_error="Enter a valid email address in the format name@example.com.",
            response_status=status.HTTP_400_BAD_REQUEST,
        )
    return _render_home_page(
        request=request,
        db=db,
        current_page="contact",
        newsletter_success=f"Thanks. We'll use {email} for product updates only.",
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
