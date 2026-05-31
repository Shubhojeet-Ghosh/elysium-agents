"""Enqueue ARQ jobs from the API or other application code."""

from arq import create_pool
from arq.connections import ArqRedis

from jobs.arq_redis import ARQ_QUEUE_NAME, get_redis_settings

_arq_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(
            get_redis_settings(),
            default_queue_name=ARQ_QUEUE_NAME,
        )
    return _arq_pool


async def close_arq_pool() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None


async def enqueue_cleanup_stale_visitors(
    *,
    threshold_seconds: int | None = None,
    emit_events: bool = True,
) -> str | None:
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "cleanup_stale_visitors",
        threshold_seconds=threshold_seconds,
        emit_events=emit_events,
    )
    return job.job_id if job else None
