"""Admin web routes for People management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.person import Person
from app.schemas.person import PersonCreate, PersonUpdate
from app.services.branding_context import load_branding_context
from app.services.person import people
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/people", tags=["web-people"])

PAGE_SIZE = 25


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
def list_people(
    request: Request,
    page: int = 1,
    email: str | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List people with pagination and optional email search."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE

    query = select(Person).order_by(Person.created_at.desc())
    if email:
        query = query.where(Person.email.ilike(f"%{email}%"))

    total = (
        db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        or 0
    )
    items = list(db.scalars(query.limit(PAGE_SIZE).offset(offset)).all())
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    ctx = _base_context(request, db, auth, title="People", page_title="People")
    ctx.update(
        {
            "people": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "email_filter": email or "",
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/people/list.html", ctx)


@router.get("/create", response_class=HTMLResponse)
def create_person_form(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the create person form."""
    ctx = _base_context(
        request, db, auth, title="Create Person", page_title="Create Person"
    )
    return templates.TemplateResponse("admin/people/create.html", ctx)


@router.post("/create", response_model=None)
async def create_person_submit(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle person creation form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        payload = PersonCreate(
            first_name=str(data.get("first_name", "")),
            last_name=str(data.get("last_name", "")),
            email=str(data.get("email", "")),
            display_name=str(data["display_name"])
            if data.get("display_name")
            else None,
            phone=str(data["phone"]) if data.get("phone") else None,
            status=str(data.get("status", "active")),
            is_active=data.get("is_active") == "on",
        )
        people.create(db, payload)
        logger.info("Created person via web: %s", payload.email)
        return RedirectResponse(
            url="/admin/people?success=Person+created+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to create person: %s", exc)
        ctx = _base_context(
            request, db, auth, title="Create Person", page_title="Create Person"
        )
        ctx["error"] = str(exc)
        ctx["form_data"] = data
        return templates.TemplateResponse("admin/people/create.html", ctx)


@router.get("/{person_id}", response_class=HTMLResponse)
def person_detail(
    request: Request,
    person_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Show person detail view."""
    person = people.get(db, str(person_id))
    ctx = _base_context(
        request,
        db,
        auth,
        title=f"{person.first_name} {person.last_name}",
        page_title="Person Detail",
    )
    ctx["person"] = person
    return templates.TemplateResponse("admin/people/detail.html", ctx)


@router.get("/{person_id}/edit", response_class=HTMLResponse)
def edit_person_form(
    request: Request,
    person_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the edit person form."""
    person = people.get(db, str(person_id))
    ctx = _base_context(
        request, db, auth, title="Edit Person", page_title="Edit Person"
    )
    ctx["person"] = person
    return templates.TemplateResponse("admin/people/edit.html", ctx)


@router.post("/{person_id}/edit", response_model=None)
async def edit_person_submit(
    request: Request,
    person_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle person edit form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        payload = PersonUpdate(
            first_name=str(data["first_name"]) if data.get("first_name") else None,
            last_name=str(data["last_name"]) if data.get("last_name") else None,
            email=str(data["email"]) if data.get("email") else None,
            display_name=str(data["display_name"])
            if data.get("display_name")
            else None,
            phone=str(data["phone"]) if data.get("phone") else None,
            status=str(data["status"]) if data.get("status") else None,
            is_active="is_active" in data,
        )
        people.update(db, str(person_id), payload)
        logger.info("Updated person via web: %s", person_id)
        return RedirectResponse(
            url=f"/admin/people/{person_id}?success=Person+updated+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to update person %s: %s", person_id, exc)
        person = db.get(Person, person_id)
        ctx = _base_context(
            request, db, auth, title="Edit Person", page_title="Edit Person"
        )
        ctx["person"] = person
        ctx["error"] = str(exc)
        return templates.TemplateResponse("admin/people/edit.html", ctx)


@router.post("/{person_id}/delete", response_model=None)
async def delete_person(
    request: Request,
    person_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle person deletion."""
    form = await request.form()
    _ = form.get("csrf_token")  # consumed for CSRF validation

    try:
        people.delete(db, str(person_id))
        logger.info("Deleted person via web: %s", person_id)
        return RedirectResponse(
            url="/admin/people?success=Person+deleted+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to delete person %s: %s", person_id, exc)
        return RedirectResponse(
            url=f"/admin/people?error={exc}",
            status_code=302,
        )
