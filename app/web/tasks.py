"""Task management web routes — kanban view with HTMX partials."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.person import Person
from app.models.task import TaskStatus
from app.schemas.task import TaskCreate as MktTaskCreate
from app.schemas.task import TaskUpdate as MktTaskUpdate
from app.services.campaign_service import CampaignService
from app.services.task_service import MktTaskService
from app.templates import templates
from app.web.deps import require_web_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["web-tasks"])


def _render_kanban(request: Request, db: Session, auth: dict) -> HTMLResponse:
    """Render just the kanban board div for HTMX swap responses."""
    from urllib.parse import parse_qs, urlparse

    task_svc = MktTaskService(db)
    campaign_svc = CampaignService(db)

    # Preserve active filters from the originating page URL
    campaign_id: UUID | None = None
    assignee_id: UUID | None = None
    current_url = request.headers.get("HX-Current-URL", "")
    if current_url:
        qs = parse_qs(urlparse(current_url).query)
        if qs.get("campaign_id") and qs["campaign_id"][0]:
            campaign_id = UUID(qs["campaign_id"][0])
        if qs.get("assignee_id") and qs["assignee_id"][0]:
            assignee_id = UUID(qs["assignee_id"][0])

    todo = task_svc.list_all(campaign_id=campaign_id, assignee_id=assignee_id, status=TaskStatus.todo, limit=100)
    in_progress = task_svc.list_all(campaign_id=campaign_id, assignee_id=assignee_id, status=TaskStatus.in_progress, limit=100)
    done = task_svc.list_all(campaign_id=campaign_id, assignee_id=assignee_id, status=TaskStatus.done, limit=100)

    ctx = {
        "request": request,
        "columns": {
            "todo": todo,
            "in_progress": in_progress,
            "done": done,
        },
        "campaigns": campaign_svc.list_all(limit=100),
    }
    return templates.TemplateResponse("tasks/partials/kanban_board.html", ctx)


@router.get("", response_class=HTMLResponse)
def task_kanban(
    request: Request,
    campaign_id: UUID | None = None,
    assignee_id: UUID | None = None,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Task kanban board — columns by status, filtered by campaign or assignee."""
    task_svc = MktTaskService(db)

    # Fetch tasks grouped by status
    todo = task_svc.list_all(
        campaign_id=campaign_id,
        assignee_id=assignee_id,
        status=TaskStatus.todo,
        limit=100,
    )
    in_progress = task_svc.list_all(
        campaign_id=campaign_id,
        assignee_id=assignee_id,
        status=TaskStatus.in_progress,
        limit=100,
    )
    done = task_svc.list_all(
        campaign_id=campaign_id,
        assignee_id=assignee_id,
        status=TaskStatus.done,
        limit=100,
    )

    # Campaigns for filter dropdown
    campaign_svc = CampaignService(db)
    campaigns = campaign_svc.list_all(limit=100)

    # Team members for assignee dropdown
    team_members = list(db.scalars(
        select(Person).where(Person.is_active.is_(True)).order_by(Person.first_name)
    ).all())

    ctx = {
        "request": request,
        "title": "Tasks",
        "columns": {
            "todo": todo,
            "in_progress": in_progress,
            "done": done,
        },
        "campaigns": campaigns,
        "team_members": team_members,
        "campaign_id_filter": str(campaign_id) if campaign_id else "",
        "assignee_id_filter": str(assignee_id) if assignee_id else "",
        "current_person_id": auth["person_id"],
        "statuses": [s.value for s in TaskStatus],
    }
    return templates.TemplateResponse("tasks/index.html", ctx)


@router.post("/create", response_model=None)
async def create_task(
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> RedirectResponse:
    """Create a task and redirect back to the kanban board."""
    form = await request.form()
    data = MktTaskCreate(
        title=str(form.get("title", "")),
        description=str(form.get("description", "")) or None,
        status=TaskStatus(str(form.get("status", "todo"))),
        campaign_id=UUID(str(form["campaign_id"])) if form.get("campaign_id") else None,
        assignee_id=UUID(str(form.get("assignee_id"))) if form.get("assignee_id") else None,
        due_date=str(form.get("due_date", "")) or None,
    )

    task_svc = MktTaskService(db)
    record = task_svc.create(data, created_by=UUID(auth["person_id"]))
    db.commit()
    logger.info("Task created via web: %s", record.id)
    return RedirectResponse(url="/tasks", status_code=302)


@router.post("/{id}/status", response_model=None)
async def update_task_status(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse | RedirectResponse:
    """Quick status update for a task. Returns kanban partial for HTMX, else redirects."""
    form = await request.form()
    new_status = form.get("status")
    if not new_status:
        return RedirectResponse(url="/tasks", status_code=302)

    try:
        status = TaskStatus(str(new_status))
    except ValueError:
        return RedirectResponse(url="/tasks", status_code=302)

    task_svc = MktTaskService(db)
    data = MktTaskUpdate(status=status)
    try:
        task_svc.update(id, data)
        db.commit()
        logger.info("Task status updated via web: %s -> %s", id, status.value)
    except ValueError:
        pass

    if request.headers.get("HX-Request"):
        return _render_kanban(request, db, auth)
    return RedirectResponse(url="/tasks", status_code=302)


@router.post("/{id}/update", response_class=HTMLResponse)
async def update_task(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Update a task (HTMX). Returns updated task card partial."""
    form = await request.form()

    update_data: dict = {}
    if form.get("title"):
        update_data["title"] = str(form["title"])
    if form.get("description") is not None:
        update_data["description"] = str(form["description"]) or None
    if form.get("status"):
        update_data["status"] = TaskStatus(str(form["status"]))
    if form.get("assignee_id"):
        update_data["assignee_id"] = UUID(str(form["assignee_id"]))
    if form.get("due_date"):
        update_data["due_date"] = str(form["due_date"])

    data = MktTaskUpdate(**update_data)

    task_svc = MktTaskService(db)
    try:
        record = task_svc.update(id, data)
        db.commit()
        logger.info("Task updated via web: %s", id)
    except ValueError:
        return HTMLResponse(content="", status_code=404)

    ctx = {"request": request, "task": record}
    return templates.TemplateResponse("tasks/partials/task_card.html", ctx)


@router.post("/{id}/delete", response_model=None)
def delete_task(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_web_auth),
) -> HTMLResponse | RedirectResponse:
    """Delete a task. Returns kanban partial for HTMX, else redirects."""
    task_svc = MktTaskService(db)
    try:
        task_svc.delete(id)
        db.commit()
        logger.info("Task deleted via web: %s", id)
    except ValueError:
        logger.warning("Task not found for delete: %s", id)

    if request.headers.get("HX-Request"):
        return _render_kanban(request, db, auth)
    return RedirectResponse(url="/tasks", status_code=302)
