"""Import task modules so Celery registers decorated tasks."""

from app.tasks.analytics_sync import analytics_sync
from app.tasks.drive_sync import drive_sync
from app.tasks.token_refresh import token_refresh

__all__ = [
    "analytics_sync",
    "drive_sync",
    "token_refresh",
]
