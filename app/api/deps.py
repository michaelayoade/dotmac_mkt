from app.db import SessionLocal
from app.services.auth_dependencies import (
    require_audit_auth,
    require_permission,
    require_role,
    require_user_auth,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = [
    "get_db",
    "require_audit_auth",
    "require_permission",
    "require_role",
    "require_user_auth",
]
