import redis
import json
from logging_config import get_logger
from config.settings import settings

logger = get_logger()

# Module-level Redis client (initialized during application startup)
redis_client = None

def get_redis_client():
    """
    Initialize and configure the Redis client.
    Raises an exception if Redis is unavailable - server will not start without Redis.
    
    Returns:
        redis.Redis: Configured Redis client
        
    Raises:
        redis.ConnectionError: If unable to connect to Redis server
    """
    client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True
    )
    client.ping()  # Test connection - will raise ConnectionError if Redis is unavailable
    logger.info(f"Connected to Redis successfully on {settings.REDIS_HOST}:{settings.REDIS_PORT} database {settings.REDIS_DB}.")
    return client

def initialize_redis_client():
    """
    Initialize the Redis client connection.
    This should be called during application startup.
    Raises an exception if Redis is unavailable - server will not start without Redis.
    
    Raises:
        RuntimeError: If unable to connect to Redis server
    """
    global redis_client
    try:
        redis_client = get_redis_client()
    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}. Server cannot start without Redis.")
        raise RuntimeError(f"Redis connection failed: {e}. Server requires Redis to be running.") from e

def close_redis_client():
    """
    Close the Redis client connection.
    This should be called during application shutdown.
    """
    global redis_client
    if redis_client is not None:
        try:
            redis_client.close()
            logger.info("Redis client connection closed.")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")
        finally:
            redis_client = None

def cache_set(data: dict, ex = None):
    """
    Cache multiple key→value pairs in Redis.
    
    Args:
        data: Dict of key–value pairs to store.
        ex: Optional expiration time in seconds for each key.
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        for key, value in data.items():
            if ex is not None:
                redis_client.set(key, json.dumps(value), ex=ex)
            else:
                redis_client.set(key, json.dumps(value))
                
    except Exception as e:
        logger.error(f"cache_set failed: {e}")
        raise

def cache_get(key: str):
    """
    Retrieve and deserialize a value from Redis.
    
    Args:
        key: The Redis key to retrieve
        
    Returns:
        Deserialized value from Redis, or None if key is not present
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        val = redis_client.get(key)
        if val is None:
            return None
        return json.loads(val)
    except json.JSONDecodeError:
        return val
    except Exception as e:
        logger.error(f"cache_get failed: {e}")
        raise

def delete_cache(key: str):
    """
    Delete a key from Redis cache.
    
    Args:
        key: The Redis key to delete.
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        redis_client.delete(key)
    except Exception as e:
        logger.error(f"delete_cache failed: {e}")
        raise
        

def cache_clear_all():
    """
    Clears all keys from Redis.
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        redis_client.flushall()
        logger.info("All Redis caches have been cleared.")
    except Exception as e:
        logger.error(f"Error while clearing Redis cache: {e}")
        raise

