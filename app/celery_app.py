from celery import Celery

from app.services.scheduler_config import get_celery_config

celery_app = Celery("dotmac_mkt")
celery_app.conf.update(get_celery_config())
# The custom DbScheduler loads schedules dynamically; keeping a raw dict in
# app.conf.beat_schedule causes Celery to mix plain dicts into scheduler state.
celery_app.conf.beat_schedule = {}
celery_app.conf.beat_scheduler = "app.celery_scheduler.DbScheduler"

# Import task modules explicitly because tasks live in app/tasks/*.py rather than
# the default app/tasks.py module layout Celery autodiscovery expects.
import app.tasks  # noqa: E402,F401
