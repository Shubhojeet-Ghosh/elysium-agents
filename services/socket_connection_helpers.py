"""
Socket connection management helpers using Redis cache
Optimized to use Redis Sets for O(1) operations instead of JSON lists
"""
from logging_config import get_logger
from services.redis_services import (
    cache_get, 
    cache_set, 
    delete_cache,
    set_add,
    set_remove,
    set_members,
    set_count,
    set_contains
)

logger = get_logger()

SOCKET_CONNECTIONS_KEY = "socket:global_connections"
USER_SOCKET_KEY_PREFIX = "socket:elysium-atlas:user_id:"


def get_socket_connections():
    """
    Get all connected socket session IDs from Redis.
    Uses Redis Set for efficient storage.
    
    Returns:
        list: List of socket session IDs
    """
    try:
        # Use Redis Set - convert set to list for compatibility
        connections_set = set_members(SOCKET_CONNECTIONS_KEY)
        return list(connections_set) if connections_set else []
    except Exception as e:
        logger.error(f"Failed to get socket connections: {e}")
        raise


def add_socket_connection(sid: str):
    """
    Add a socket session ID to the global connections set in Redis.
    Uses Redis Set for O(1) add operation - much faster than JSON list.
    
    Args:
        sid: Socket session ID to add
    """
    try:
        logger.info(f"Adding socket connection: {sid} to the global connections set.")
        # Redis SADD returns number of members added (0 if already exists)
        added_count = set_add(SOCKET_CONNECTIONS_KEY, sid)
        if added_count > 0:
            logger.debug(f"Added socket connection: {sid}")
        else:
            logger.debug(f"Socket connection {sid} already exists")
    except Exception as e:
        logger.error(f"Failed to add socket connection {sid}: {e}")
        raise


def remove_socket_connection(sid: str):
    """
    Remove a socket session ID from the global connections set in Redis.
    Uses Redis Set for O(1) remove operation - much faster than JSON list.
    
    Args:
        sid: Socket session ID to remove
    """
    try:
        # Redis SREM returns number of members removed (0 if not found)
        removed_count = set_remove(SOCKET_CONNECTIONS_KEY, sid)
        if removed_count > 0:
            logger.debug(f"Removed socket connection: {sid}")
        else:
            logger.debug(f"Socket connection {sid} not found in set")
    except Exception as e:
        logger.error(f"Failed to remove socket connection {sid}: {e}")
        raise


def get_socket_connections_count():
    """
    Get the count of connected socket session IDs.
    Uses Redis SCARD for O(1) operation - extremely fast, doesn't retrieve full list.
    
    Returns:
        int: Number of connected sockets
    """
    try:
        # Redis SCARD is O(1) - much faster than retrieving and counting the full list
        count = set_count(SOCKET_CONNECTIONS_KEY)
        return count
    except Exception as e:
        logger.error(f"Failed to get socket connections count: {e}")
        raise


def get_user_id_from_user_data(user_data: dict) -> str | None:
    """
    Extract user_id from user_data dictionary.
    Checks multiple possible field names for user_id.
    
    Args:
        user_data: Dictionary containing user information
        
    Returns:
        str: User ID if found, None otherwise
    """
    if not user_data or not isinstance(user_data, dict):
        return None
    
    # Try different possible field names
    user_id = (
        user_data.get("user_id") or 
        user_data.get("userId") or 
        user_data.get("id")
    )
    
    if user_id:
        return str(user_id).strip()
    
    return None


def add_user_socket_mapping(user_data: dict, sid: str):
    """
    Add a socket ID to the user's socket list in Redis.
    Creates a key pattern: socket:elysium-atlas:user_id:{user_id}
    Value is a list of socket IDs associated with that user.
    
    Args:
        user_data: Dictionary containing user information (must have user_id)
        sid: Socket session ID to add
    """
    try:
        user_id = get_user_id_from_user_data(user_data)
        if not user_id:
            logger.warning(f"Could not extract user_id from user_data, skipping socket mapping for {sid}")
            return
        
        redis_key = f"{USER_SOCKET_KEY_PREFIX}{user_id}"
        
        # Get existing socket IDs for this user
        existing_sockets = cache_get(redis_key)
        if existing_sockets is None:
            existing_sockets = []
        
        # Ensure it's a list
        if not isinstance(existing_sockets, list):
            logger.warning(f"Invalid data format in Redis key {redis_key}, resetting to empty list")
            existing_sockets = []
        
        # Add socket ID if not already present
        if sid not in existing_sockets:
            existing_sockets.append(sid)
            cache_set({redis_key: existing_sockets})
            logger.info(f"Added socket {sid} to user {user_id} mapping. Total sockets : {len(existing_sockets)}")
        else:
            logger.debug(f"Socket {sid} already exists in user {user_id} mapping")
            
    except Exception as e:
        logger.error(f"Failed to add user socket mapping for socket {sid}: {e}")
        raise


def remove_user_socket_mapping(user_id: str, sid: str):
    """
    Remove a socket ID from the user's socket list in Redis.
    If the list becomes empty, optionally delete the key.
    
    Args:
        user_id: User ID to remove socket from
        sid: Socket session ID to remove
    """
    try:
        if not user_id:
            logger.warning(f"Invalid user_id provided, skipping socket removal for {sid}")
            return
        
        redis_key = f"{USER_SOCKET_KEY_PREFIX}{user_id}"
        
        # Get existing socket IDs for this user
        existing_sockets = cache_get(redis_key)
        if existing_sockets is None:
            logger.debug(f"No socket mapping found for user {user_id}, socket {sid} may have already been removed")
            return
        
        # Ensure it's a list
        if not isinstance(existing_sockets, list):
            logger.warning(f"Invalid data format in Redis key {redis_key}, deleting key")
            delete_cache(redis_key)
            return
        
        # Remove socket ID if present
        if sid in existing_sockets:
            existing_sockets.remove(sid)
            
            # If list is empty, delete the key, otherwise update it
            if len(existing_sockets) == 0:
                delete_cache(redis_key)
                logger.info(f"Removed socket {sid} from user {user_id} mapping. No sockets remaining, deleted key.")
            else:
                cache_set({redis_key: existing_sockets})
                logger.info(f"Removed socket {sid} from user {user_id} mapping. Remaining sockets : {len(existing_sockets)}")
        else:
            logger.debug(f"Socket {sid} not found in user {user_id} mapping")
            
    except Exception as e:
        logger.error(f"Failed to remove user socket mapping for socket {sid} and user {user_id}: {e}")
        raise


def get_user_socket_ids(user_id: str) -> list:
    """
    Get all socket IDs associated with a user ID.
    
    Args:
        user_id: User ID to get sockets for
        
    Returns:
        list: List of socket IDs for the user, empty list if none found
    """
    try:
        if not user_id:
            return []
        
        redis_key = f"{USER_SOCKET_KEY_PREFIX}{user_id}"
        socket_ids = cache_get(redis_key)
        
        if socket_ids is None:
            return []
        
        if not isinstance(socket_ids, list):
            logger.warning(f"Invalid data format in Redis key {redis_key}")
            return []
        
        return socket_ids
        
    except Exception as e:
        logger.error(f"Failed to get user socket IDs for user {user_id}: {e}")
        raise
