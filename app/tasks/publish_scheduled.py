"""Periodic task: publish posts with scheduled_at <= now."""

import logging

from app.celery_app import celery_app
from app.db import SessionLocal
from app.services.publishing_service import PublishingService

logger = logging.getLogger(__name__)


@celery_app.task(name="publish_scheduled", ignore_result=True)
def publish_scheduled():
    """Find posts with status=planned and scheduled_at <= now(), publish them.

    Schedule: every 60 seconds via Celery Beat.
    """
    db = SessionLocal()
    try:
        svc = PublishingService(db)
        published_ids = svc.publish_due_posts()
        db.commit()
        if published_ids:
            logger.info("Published %d scheduled posts", len(published_ids))
    except Exception:
        db.rollback()
        logger.exception("publish_scheduled task failed")
        raise
    finally:
        db.close()
