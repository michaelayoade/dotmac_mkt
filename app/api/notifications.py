from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user_auth
from app.schemas.common import ListResponse
from app.schemas.notification import (
    NotificationCreate,
    NotificationRead,
    UnreadCountResponse,
)
from app.services.notification import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("", response_model=NotificationRead, status_code=status.HTTP_201_CREATED)
def create_notification(
    payload: NotificationCreate,
    db: Session = Depends(get_db),
) -> NotificationRead:
    svc = NotificationService(db)
    record = svc.create(payload)
    db.commit()
    return NotificationRead.model_validate(record)


@router.get("/me", response_model=ListResponse[NotificationRead])
def list_my_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    auth: dict = Depends(require_user_auth),
) -> ListResponse[NotificationRead]:
    person_id = UUID(auth["person_id"])
    svc = NotificationService(db)
    items = svc.list_for_recipient(
        person_id, unread_only=unread_only, limit=limit, offset=offset
    )
    total = svc.unread_count(person_id) if unread_only else len(items)
    return ListResponse(
        items=[NotificationRead.model_validate(n) for n in items],
        count=len(items),
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get("/me/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    auth: dict = Depends(require_user_auth),
) -> UnreadCountResponse:
    person_id = UUID(auth["person_id"])
    svc = NotificationService(db)
    count = svc.unread_count(person_id)
    return UnreadCountResponse(count=count)


@router.post("/me/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_user_auth),
) -> NotificationRead:
    person_id = UUID(auth["person_id"])
    svc = NotificationService(db)
    record = svc.mark_read(notification_id, person_id)
    if not record:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Notification not found")
    db.commit()
    return NotificationRead.model_validate(record)


@router.post("/me/read-all", status_code=status.HTTP_200_OK)
def mark_all_read(
    db: Session = Depends(get_db),
    auth: dict = Depends(require_user_auth),
) -> dict[str, int]:
    person_id = UUID(auth["person_id"])
    svc = NotificationService(db)
    count = svc.mark_all_read(person_id)
    db.commit()
    return {"marked_read": count}
