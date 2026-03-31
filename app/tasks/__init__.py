"""Import task modules so Celery registers decorated tasks."""

from app.tasks.ad_sync import ad_sync
from app.tasks.analytics_sync import analytics_sync
from app.tasks.drive_sync import drive_sync
from app.tasks.publish_scheduled import publish_scheduled
from app.tasks.token_refresh import token_refresh

__all__ = [
    "ad_sync",
    "analytics_sync",
    "drive_sync",
    "publish_scheduled",
    "token_refresh",
]
