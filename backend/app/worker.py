from celery import Celery

from app.config import get_settings


def _create_celery() -> Celery:
    settings = get_settings()
    app = Celery("atlas", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )
    return app


celery_app = _create_celery()
