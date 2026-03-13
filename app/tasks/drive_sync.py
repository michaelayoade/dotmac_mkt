import logging

from app.celery_app import celery_app
from app.db import SessionLocal
from app.services.drive_service import DriveService

logger = logging.getLogger(__name__)


@celery_app.task(name="drive_sync", ignore_result=True)
def drive_sync():
    """Sync assets from Google Drive marketing folder."""
    db = SessionLocal()
    try:
        svc = DriveService(db)
        if not svc.is_configured():
            logger.debug("Drive not configured, skipping sync")
            return

        result = svc.sync_folder()
        db.commit()
        logger.info(
            "Drive sync: created=%d updated=%d missing=%d",
            result["created"],
            result["updated"],
            result["missing"],
        )
    except Exception:
        db.rollback()
        logger.exception("Drive sync failed")
        raise
    finally:
        db.close()
