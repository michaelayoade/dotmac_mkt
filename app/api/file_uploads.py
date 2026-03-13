from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.common import ListResponse
from app.schemas.file_upload import FileUploadRead
from app.services.file_upload import FileUploadService

router = APIRouter(prefix="/file-uploads", tags=["file-uploads"])


@router.post("", response_model=FileUploadRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    category: str = Form(default="document"),
    entity_type: str | None = Form(default=None),
    entity_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> FileUploadRead:
    content = await file.read()
    svc = FileUploadService(db)
    record = svc.upload(
        content=content,
        filename=file.filename or "unknown",
        content_type=file.content_type or "application/octet-stream",
        category=category,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.commit()
    return FileUploadRead.model_validate(record)


@router.get("/{file_id}", response_model=FileUploadRead)
def get_file_upload(file_id: UUID, db: Session = Depends(get_db)) -> FileUploadRead:
    svc = FileUploadService(db)
    record = svc.get_by_id(file_id)
    if not record or not record.is_active:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="File upload not found")
    return FileUploadRead.model_validate(record)


@router.get("", response_model=ListResponse[FileUploadRead])
def list_file_uploads(
    category: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ListResponse[FileUploadRead]:
    svc = FileUploadService(db)
    items = svc.list_uploads(
        category=category,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
    total = svc.count(category=category)
    return ListResponse(
        items=[FileUploadRead.model_validate(i) for i in items],
        count=len(items),
        limit=limit,
        offset=offset,
        total=total,
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file_upload(file_id: UUID, db: Session = Depends(get_db)) -> None:
    svc = FileUploadService(db)
    svc.delete(file_id)
    db.commit()
