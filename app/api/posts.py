"""Post API endpoints — reschedule support for calendar drag-drop."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts", tags=["posts"])


class RescheduleRequest(BaseModel):
    scheduled_at: datetime


@router.patch("/{post_id}/reschedule")
def reschedule_post(
    post_id: UUID,
    body: RescheduleRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_user_auth),
) -> dict:
    """Reschedule a post to a new date/time."""
    from app.services.post_service import PostService

    post_svc = PostService(db)
    try:
        record = post_svc.reschedule(post_id, body.scheduled_at)
        db.commit()
        logger.info("Post rescheduled via API: %s -> %s", post_id, body.scheduled_at)
        return {"id": str(record.id), "scheduled_at": record.scheduled_at.isoformat()}
    except ValueError:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Post not found")
