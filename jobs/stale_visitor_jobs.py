"""Background jobs for stale visitor cleanup."""

from typing import Any, Dict

from logging_config import get_logger
from services.elysium_atlas_services.atlas_stale_visitor_services import cleanup_stale_visitors_service

logger = get_logger()


async def cleanup_stale_visitors(
    ctx,
    *,
    threshold_seconds: int | None = None,
    emit_events: bool = True,
) -> Dict[str, Any]:
    """
    ARQ job: remove stale visitors from Redis and mark them offline in MongoDB.

    Scheduled via cron in jobs.worker_settings.WorkerSettings.
    Can also be enqueued on demand via jobs.enqueue.enqueue_cleanup_stale_visitors.
    """
    logger.info("ARQ job cleanup_stale_visitors started")
    result = await cleanup_stale_visitors_service(
        threshold_seconds=threshold_seconds,
        emit_events=emit_events,
    )
    logger.info(f"ARQ job cleanup_stale_visitors finished: {result}")
    return result
