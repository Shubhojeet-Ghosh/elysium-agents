"""Shared ARQ / Redis queue configuration."""

from arq.connections import RedisSettings

from config.settings import settings

# Must match WorkerSettings.queue_name and create_pool(default_queue_name=...)
ARQ_QUEUE_NAME = "arq:elysium-agents:queue"


def get_redis_settings() -> RedisSettings:
    return RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        database=settings.REDIS_DB,
    )
