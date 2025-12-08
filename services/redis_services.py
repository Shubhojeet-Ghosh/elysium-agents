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


# Redis Set operations for efficient socket connection management
def set_add(key: str, *members):
    """
    Add one or more members to a Redis Set.
    O(1) per operation.
    
    Args:
        key: Redis key for the set
        *members: One or more members to add to the set
        
    Returns:
        int: Number of members that were added (not already present)
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        return redis_client.sadd(key, *members)
    except Exception as e:
        logger.error(f"set_add failed for key {key}: {e}")
        raise


def set_remove(key: str, *members):
    """
    Remove one or more members from a Redis Set.
    O(1) per operation.
    
    Args:
        key: Redis key for the set
        *members: One or more members to remove from the set
        
    Returns:
        int: Number of members that were removed
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        return redis_client.srem(key, *members)
    except Exception as e:
        logger.error(f"set_remove failed for key {key}: {e}")
        raise


def set_members(key: str):
    """
    Get all members of a Redis Set.
    O(N) where N is the number of members.
    
    Args:
        key: Redis key for the set
        
    Returns:
        set: Set of all members, empty set if key doesn't exist
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        members = redis_client.smembers(key)
        return members if members is not None else set()
    except Exception as e:
        logger.error(f"set_members failed for key {key}: {e}")
        raise


def set_count(key: str):
    """
    Get the number of members in a Redis Set.
    O(1) operation - very efficient for getting count.
    
    Args:
        key: Redis key for the set
        
    Returns:
        int: Number of members in the set, 0 if key doesn't exist
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        count = redis_client.scard(key)
        return count if count is not None else 0
    except Exception as e:
        logger.error(f"set_count failed for key {key}: {e}")
        raise


def set_contains(key: str, member):
    """
    Check if a member exists in a Redis Set.
    O(1) operation.
    
    Args:
        key: Redis key for the set
        member: Member to check
        
    Returns:
        bool: True if member exists, False otherwise
    """
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call initialize_redis_client() first.")
    try:
        return bool(redis_client.sismember(key, member))
    except Exception as e:
        logger.error(f"set_contains failed for key {key}: {e}")
        raise