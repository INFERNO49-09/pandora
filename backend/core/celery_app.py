from celery import Celery
from celery.schedules import crontab
from core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "pandora",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "ingestion.tasks",
        "extraction.tasks",
        "discovery.tasks",
        "graph_ml.tasks.ml_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    task_routes={
        "ingestion.tasks.*":     {"queue": "ingestion"},
        "extraction.tasks.*":    {"queue": "extraction"},
        "discovery.tasks.*":     {"queue": "discovery"},
        "graph_ml.tasks.*":      {"queue": "discovery"},
    },

    beat_schedule={
        # Ingestion
        "hourly-ingestion-check": {
            "task":     "ingestion.tasks.run_ingestion_cycle",
            "schedule": crontab(minute=0),
        },
        # Discovery
        "nightly-discovery-scan": {
            "task":     "discovery.tasks.run_full_discovery_scan",
            "schedule": crontab(hour=2, minute=0),
        },
        "nightly-contradiction-scan": {
            "task":     "discovery.tasks.run_contradiction_scan",
            "schedule": crontab(hour=4, minute=0),
        },
        # Graph ML
        "weekly-model-training": {
            "task":     "graph_ml.tasks.train_all_models",
            "schedule": crontab(hour=3, minute=0, day_of_week=0),  # Sunday 3 AM
        },
        "nightly-embedding-refresh": {
            "task":     "graph_ml.tasks.refresh_embeddings",
            "schedule": crontab(hour=3, minute=30),
        },
    },
)
