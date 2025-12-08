"""
Socket.IO configuration and event handlers
"""

import socketio
from socketio import AsyncRedisManager

from logging_config import get_logger
from config.settings import settings
from middlewares.socket_auth import extract_token_from_socket_environ

from services.socket_connection_helpers import (
    add_socket_connection,
    remove_socket_connection,
    add_user_socket_mapping,
    remove_user_socket_mapping,
    get_user_id_from_user_data
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
async def connect(sid, environ, auth):
    try:
        logger.info(f"New client connected: {sid}.")
        add_socket_connection(sid)

        user_data = extract_token_from_socket_environ(environ,auth)
        logger.info(f"User data extracted from token: {user_data}")

        if(user_data):
            # logger.info(f"Saving socketuser data to session: {user_data}")
            await sio.save_session(sid, {"user_data": user_data})
            
            # Add socket ID to user's socket mapping in Redis
            add_user_socket_mapping(user_data, sid)

    except Exception as e:
        logger.error(f"Error adding socket connection {sid}: {e}")


# Handle 'disconnect' event
@sio.on("disconnect")
async def disconnect(sid):
    try:
        # Get user_data from session to remove socket mapping
        session = await sio.get_session(sid)
        user_data = session.get("user_data") if session else None
        
        if user_data:
            user_id = get_user_id_from_user_data(user_data)
            if user_id:
                remove_user_socket_mapping(user_id, sid)
        
        remove_socket_connection(sid)
        logger.info(f"Client disconnected: {sid}.")
    except Exception as e:
        logger.error(f"Error removing socket connection {sid}: {e}")