"""Admin web routes for Scheduled Task management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.scheduler import ScheduledTask
from app.schemas.scheduler import ScheduledTaskCreate, ScheduledTaskUpdate
from app.services.branding_context import load_branding_context
from app.services.scheduler import scheduled_tasks
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scheduler", tags=["web-scheduler"])

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
def list_scheduled_tasks(
    request: Request,
    page: int = 1,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """List scheduled tasks with pagination."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE

    query = select(ScheduledTask).order_by(ScheduledTask.created_at.desc())
    total = (
        db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        or 0
    )
    items = list(db.scalars(query.limit(PAGE_SIZE).offset(offset)).all())
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    ctx = _base_context(
        request, db, auth, title="Scheduled Tasks", page_title="Scheduled Tasks"
    )
    ctx.update(
        {
            "tasks": items,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse("admin/scheduler/list.html", ctx)


@router.get("/create", response_class=HTMLResponse)
def create_task_form(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the create scheduled task form."""
    ctx = _base_context(
        request,
        db,
        auth,
        title="Create Scheduled Task",
        page_title="Create Scheduled Task",
    )
    return templates.TemplateResponse("admin/scheduler/create.html", ctx)


@router.post("/create", response_model=None)
async def create_task_submit(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle scheduled task creation form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        interval = int(str(data.get("interval_seconds", "3600")))
        payload = ScheduledTaskCreate(
            name=str(data.get("name", "")),
            task_name=str(data.get("task_name", "")),
            interval_seconds=interval,
            enabled=data.get("enabled") == "on",
        )
        scheduled_tasks.create(db, payload)
        logger.info("Created scheduled task via web: %s", payload.name)
        return RedirectResponse(
            url="/admin/scheduler?success=Task+created+successfully",
            status_code=302,
        )
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to create scheduled task: %s", exc)
        ctx = _base_context(
            request,
            db,
            auth,
            title="Create Scheduled Task",
            page_title="Create Scheduled Task",
        )
        ctx["error"] = str(exc)
        ctx["form_data"] = data
        return templates.TemplateResponse("admin/scheduler/create.html", ctx)
    except Exception as exc:
        logger.warning("Failed to create scheduled task: %s", exc)
        ctx = _base_context(
            request,
            db,
            auth,
            title="Create Scheduled Task",
            page_title="Create Scheduled Task",
        )
        ctx["error"] = str(exc)
        ctx["form_data"] = data
        return templates.TemplateResponse("admin/scheduler/create.html", ctx)


@router.get("/{task_id}/edit", response_class=HTMLResponse)
def edit_task_form(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Render the edit scheduled task form."""
    task = scheduled_tasks.get(db, str(task_id))
    ctx = _base_context(
        request,
        db,
        auth,
        title="Edit Scheduled Task",
        page_title="Edit Scheduled Task",
    )
    ctx["task"] = task
    return templates.TemplateResponse("admin/scheduler/edit.html", ctx)


@router.post("/{task_id}/edit", response_model=None)
async def edit_task_submit(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse | HTMLResponse:
    """Handle scheduled task edit form submission."""
    form = await request.form()
    data = dict(form)
    data.pop("csrf_token", None)

    try:
        interval_raw = data.get("interval_seconds")
        interval = int(str(interval_raw)) if interval_raw else None
        payload = ScheduledTaskUpdate(
            name=str(data["name"]) if data.get("name") else None,
            task_name=str(data["task_name"]) if data.get("task_name") else None,
            interval_seconds=interval,
            enabled="enabled" in data,
        )
        scheduled_tasks.update(db, str(task_id), payload)
        logger.info("Updated scheduled task via web: %s", task_id)
        return RedirectResponse(
            url="/admin/scheduler?success=Task+updated+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to update scheduled task %s: %s", task_id, exc)
        task = db.get(ScheduledTask, task_id)
        ctx = _base_context(
            request,
            db,
            auth,
            title="Edit Scheduled Task",
            page_title="Edit Scheduled Task",
        )
        ctx["task"] = task
        ctx["error"] = str(exc)
        return templates.TemplateResponse("admin/scheduler/edit.html", ctx)


@router.post("/{task_id}/delete", response_model=None)
async def delete_task(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Handle scheduled task deletion."""
    form = await request.form()
    _ = form.get("csrf_token")

    try:
        scheduled_tasks.delete(db, str(task_id))
        logger.info("Deleted scheduled task via web: %s", task_id)
        return RedirectResponse(
            url="/admin/scheduler?success=Task+deleted+successfully",
            status_code=302,
        )
    except Exception as exc:
        logger.warning("Failed to delete scheduled task %s: %s", task_id, exc)
        return RedirectResponse(
            url=f"/admin/scheduler?error={exc}",
            status_code=302,
        )
