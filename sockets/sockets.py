"""
Socket.IO configuration and event handlers
"""

import socketio
from socketio import AsyncRedisManager

from logging_config import get_logger
from config.settings import settings
from services.socket_connection_helpers import (
    add_socket_connection,
    remove_socket_connection,
    get_socket_connections,
    get_socket_connections_count
)
logger = get_logger()

REDIS_URL = f'redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}'

# Create a Redis manager (edit the URL if your Redis is elsewhere)
mgr = AsyncRedisManager(REDIS_URL)

# Create Socket.IO instance
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi", manager=mgr)

# Create ASGI app for Socket.IO
socketio_app = socketio.ASGIApp(sio)

# Handle 'connect' event
@sio.on("connect")
async def connect(sid, environ):
    try:
        add_socket_connection(sid)
        total_connections = get_socket_connections_count()
        logger.info(f"New client connected: {sid}. Total connected clients: {total_connections}")
    except Exception as e:
        logger.error(f"Error adding socket connection {sid}: {e}")


# Handle 'disconnect' event
@sio.on("disconnect")
async def disconnect(sid):
    try:
        remove_socket_connection(sid)
        total_connections = get_socket_connections_count()
        logger.info(f"Client disconnected: {sid}. Total connected clients: {total_connections}")
    except Exception as e:
        logger.error(f"Error removing socket connection {sid}: {e}")


@sio.on("mark-online")
async def register_user(sid, data):
    """Handles user registration event and broadcasts to all other clients."""
    
    logger.info(f"Received mark-online event from {sid}: {data}")
    
    # Validate incoming data format
    if not isinstance(data, dict) or "session_id" not in data:
        logger.warning("Invalid data format received")
        return
    
    session_id = data["session_id"]
    
    # Broadcast to all other clients that a new user has joined
    try:
        connected_clients = get_socket_connections()
        total_connections = get_socket_connections_count()
        
        if len(connected_clients) > 1:  # Only broadcast if there are other clients
            await sio.emit(
                "user-joined",
                {
                    "socket_id": sid,
                    "session_id": session_id,
                    "total_connections": total_connections
                },
                skip_sid=sid  # Don't send to the newly registered client
            )
            logger.info(f"Broadcasted new user join (socket: {sid}, session: {session_id}) to {len(connected_clients) - 1} other clients")
        else:
            logger.info(f"User registered (socket: {sid}, session: {session_id}) but no other clients to notify")
    except Exception as e:
        logger.error(f"Error broadcasting user join for {sid}: {e}")

