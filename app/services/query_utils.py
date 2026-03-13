from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def apply_ordering(
    query: Any, order_by: str, order_dir: str, allowed_columns: dict[str, Any]
) -> Any:
    if order_by not in allowed_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid order_by. Allowed: {', '.join(sorted(allowed_columns))}",
        )
    column = allowed_columns[order_by]
    if order_dir == "desc":
        return query.order_by(column.desc())
    return query.order_by(column.asc())


def apply_pagination(query: Any, limit: int, offset: int) -> Any:
    return query.limit(limit).offset(offset)


def validate_enum(value: Any, enum_cls: Any, label: str) -> Any:
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}") from exc
