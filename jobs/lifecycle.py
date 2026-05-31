"""ARQ worker startup and shutdown hooks."""

from logging_config import get_logger
from services.mongo_services import close_mongo_client, initialize_mongo_client
from services.redis_services import close_redis_client, initialize_redis_client

logger = get_logger()


async def startup(ctx) -> None:
    """Initialize shared clients once per worker process."""
    initialize_redis_client()
    await initialize_mongo_client()
    logger.info("ARQ worker startup complete (Redis + MongoDB ready)")


async def shutdown(ctx) -> None:
    """Release shared clients when the worker stops."""
    await close_mongo_client()
    close_redis_client()
    logger.info("ARQ worker shutdown complete")
