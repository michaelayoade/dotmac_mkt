"""Task management web routes — kanban view with HTMX partials."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.task import TaskStatus
from app.schemas.task import TaskCreate as MktTaskCreate
from app.schemas.task import TaskUpdate as MktTaskUpdate
from app.services.campaign_service import CampaignService
from app.services.task_service import MktTaskService
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["web-tasks"])

# TODO: get from auth context
PLACEHOLDER_USER_ID = UUID("00000000-0000-0000-0000-000000000000")


@router.get("", response_class=HTMLResponse)
def task_kanban(
    request: Request,
    campaign_id: UUID | None = None,
    assignee_id: UUID | None = None,
    db: Session = Depends(get_db),
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

    ctx = {
        "request": request,
        "title": "Tasks",
        "columns": {
            "todo": todo,
            "in_progress": in_progress,
            "done": done,
        },
        "campaigns": campaigns,
        "campaign_id_filter": str(campaign_id) if campaign_id else "",
        "assignee_id_filter": str(assignee_id) if assignee_id else "",
        "statuses": [s.value for s in TaskStatus],
    }
    return templates.TemplateResponse("tasks/index.html", ctx)


@router.post("/create", response_class=HTMLResponse)
async def create_task(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Create a task (HTMX). Returns a task card partial."""
    form = await request.form()
    data = MktTaskCreate(
        title=str(form.get("title", "")),
        description=str(form.get("description", "")) or None,
        status=TaskStatus(str(form.get("status", "todo"))),
        campaign_id=UUID(str(form.get("campaign_id", ""))),
        assignee_id=UUID(str(form.get("assignee_id"))) if form.get("assignee_id") else None,
        due_date=str(form.get("due_date", "")) or None,
    )

    task_svc = MktTaskService(db)
    # TODO: get from auth context
    record = task_svc.create(data, created_by=PLACEHOLDER_USER_ID)
    db.commit()
    logger.info("Task created via web: %s", record.id)

    ctx = {"request": request, "task": record}
    return templates.TemplateResponse("tasks/partials/task_card.html", ctx)


@router.post("/{id}/update", response_class=HTMLResponse)
async def update_task(
    request: Request,
    id: UUID,
    db: Session = Depends(get_db),
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


@router.post("/{id}/delete", response_class=HTMLResponse)
def delete_task(
    id: UUID,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Delete a task (HTMX). Returns empty response."""
    task_svc = MktTaskService(db)
    try:
        task_svc.delete(id)
        db.commit()
        logger.info("Task deleted via web: %s", id)
    except ValueError:
        pass
    return HTMLResponse(content="")
