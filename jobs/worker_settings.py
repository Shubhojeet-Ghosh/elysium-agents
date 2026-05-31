"""
ARQ worker entry point.

Run as a separate process (one instance for cron + job processing):

    arq jobs.worker_settings.WorkerSettings

Or:

    python -m arq jobs.worker_settings.WorkerSettings
"""

from arq import cron

from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from jobs.arq_redis import ARQ_QUEUE_NAME, get_redis_settings
from jobs.lifecycle import shutdown, startup
from jobs.stale_visitor_jobs import cleanup_stale_visitors


def get_stale_visitor_cleanup_interval_minutes() -> int:
    config = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("scheduler_config", {})
    return int(config.get("stale_visitor_cleanup_interval_minutes", 15))


def cron_minutes_every_n(interval_minutes: int) -> set[int]:
    """Build minute={0, n, 2n, ...} for ARQ cron."""
    interval = max(1, min(59, interval_minutes))
    return set(range(0, 60, interval))


_cleanup_interval_minutes = get_stale_visitor_cleanup_interval_minutes()


class WorkerSettings:
    """Configuration consumed by the `arq` CLI."""

    functions = [cleanup_stale_visitors]

    on_startup = startup
    on_shutdown = shutdown

    redis_settings = get_redis_settings()
    queue_name = ARQ_QUEUE_NAME

    max_jobs = 2
    job_timeout = 300
    keep_result = 3600

    cron_jobs = [
        cron(
            cleanup_stale_visitors,
            minute=cron_minutes_every_n(_cleanup_interval_minutes),
            unique=True,
            timeout=300,
        ),
    ]
