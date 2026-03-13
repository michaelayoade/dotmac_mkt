"""Shared service utilities: UUID coercion, ordering, pagination."""

from __future__ import annotations

import math
import uuid
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


def coerce_uuid(value: Any) -> uuid.UUID | None:
    """Convert a string or UUID to UUID, or return None."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def apply_ordering(
    query: Select[Any],
    order_by: str,
    order_dir: str,
    allowed_columns: dict[str, Any],
) -> Select[Any]:
    """Apply ordering to a select statement with validation."""
    if order_by not in allowed_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid order_by. Allowed: {', '.join(sorted(allowed_columns))}",
        )
    column = allowed_columns[order_by]
    if order_dir == "desc":
        return query.order_by(column.desc())
    return query.order_by(column.asc())


def apply_pagination(query: Select[Any], limit: int, offset: int) -> Select[Any]:
    """Apply limit/offset to a select statement."""
    return query.limit(limit).offset(offset)


def paginate(
    db: Session,
    query: Select[Any],
    *,
    page: int = 1,
    page_size: int = 25,
    max_page_size: int = 100,
) -> dict[str, Any]:
    """Execute a query with pagination and return a standardized response.

    Returns:
        {
            "items": [...],
            "total": 150,
            "page": 1,
            "page_size": 25,
            "pages": 6,
        }
    """
    page = max(1, page)
    page_size = min(max(1, page_size), max_page_size)
    offset = (page - 1) * page_size

    # Count total matching rows (strip ordering for efficiency)
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = db.scalar(count_query) or 0

    # Fetch page
    items = list(db.scalars(query.limit(page_size).offset(offset)).all())

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if page_size else 0,
    }
