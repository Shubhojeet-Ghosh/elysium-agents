"""
Socket connection management helpers using Redis cache
"""
from logging_config import get_logger
from services.redis_services import cache_get, cache_set

logger = get_logger()

SOCKET_CONNECTIONS_KEY = "socket:global_connections"


def get_socket_connections():
    """
    Get all connected socket session IDs from Redis.
    
    Returns:
        list: List of socket session IDs
    """
    try:
        connections = cache_get(SOCKET_CONNECTIONS_KEY)
        return connections if connections is not None else []
    except Exception as e:
        logger.error(f"Failed to get socket connections: {e}")
        raise


def add_socket_connection(sid: str):
    """
    Add a socket session ID to the global connections list in Redis.
    
    Args:
        sid: Socket session ID to add
    """
    try:
        connections = get_socket_connections()
        if sid not in connections:
            connections.append(sid)
            cache_set({SOCKET_CONNECTIONS_KEY: connections})
            logger.debug(f"Added socket connection: {sid}")
        else:
            logger.debug(f"Socket connection {sid} already exists")
    except Exception as e:
        logger.error(f"Failed to add socket connection {sid}: {e}")
        raise


def remove_socket_connection(sid: str):
    """
    Remove a socket session ID from the global connections list in Redis.
    
    Args:
        sid: Socket session ID to remove
    """
    try:
        connections = get_socket_connections()
        if sid in connections:
            connections.remove(sid)
            cache_set({SOCKET_CONNECTIONS_KEY: connections})
            logger.debug(f"Removed socket connection: {sid}")
        else:
            logger.debug(f"Socket connection {sid} not found in list")
    except Exception as e:
        logger.error(f"Failed to remove socket connection {sid}: {e}")
        raise


def get_socket_connections_count():
    """
    Get the count of connected socket session IDs.
    
    Returns:
        int: Number of connected sockets
    """
    try:
        connections = get_socket_connections()
        return len(connections)
    except Exception as e:
        logger.error(f"Failed to get socket connections count: {e}")
        raise

