"""
Socket.IO configuration and event handlers
"""

import socketio
from socketio import AsyncRedisManager

from logging_config import get_logger
from config.settings import settings
from middlewares.socket_auth import extract_token_from_socket_environ
from controllers.elysium_atlas_controller_files.atlas_chat_controllers import chat_with_agent_controller_v1

from services.socket_connection_helpers import (
    add_socket_connection,
    remove_socket_connection,
    add_user_socket_mapping,
    remove_user_socket_mapping,
    get_user_id_from_user_data
)
from services.elysium_atlas_services.atlas_visitor_socket_services import handle_atlas_visitor_connected_service

logger = get_logger()

REDIS_URL = f'redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}'

# Create a Redis manager (edit the URL if your Redis is elsewhere)
mgr = AsyncRedisManager(
    REDIS_URL,
    write_only=False,
    channel="socketio",
)

# Create Socket.IO instance
sio = socketio.AsyncServer(
    cors_allowed_origins="*",
    async_mode="asgi",
    manager=mgr,
    ping_interval=25,
    ping_timeout=60,
)

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
            
            # Join socket to user's room for broadcasting
            # user_id = get_user_id_from_user_data(user_data)
            # if user_id:
            #     await sio.enter_room(sid, user_id)
            #     logger.info(f"Socket {sid} joined room {user_id}")

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
                # # Leave user's room
                # await sio.leave_room(sid, user_id)
                # logger.info(f"Socket {sid} left room {user_id}")
                remove_user_socket_mapping(user_id, sid)
        
        # Check if it's a visitor and remove from agent Redis
        agent_id = session.get("agent_id") if session else None
        if agent_id:
            logger.info(f"Removing visitor socket {sid} from agent {agent_id} visitors")
            from services.elysium_atlas_services.atlas_redis_services import remove_visitor_from_agent
            remove_visitor_from_agent(agent_id, sid)
        
        remove_socket_connection(sid)
        logger.info(f"Client disconnected: {sid}.")
    except Exception as e:
        logger.error(f"Error removing socket connection {sid}: {e}")


# Handle 'atlas-visitor-message' event - main chat orchestrator for atlas users
@sio.on("atlas-visitor-message")
async def handle_atlas_visitor_message(sid,socketData):
    logger.info("Event 'atlas-visitor-message' received")
    session = await sio.get_session(sid)
    user_data = session.get("user_data") if session else None
    logger.info(user_data)

    response = await chat_with_agent_controller_v1(socketData, user_data, sid)

# Handle 'atlas-visitor-connected' event
@sio.on("atlas-visitor-connected")
async def handle_atlas_visitor_connected(sid, socketData):
    
    # Save agent_id to session for disconnect handling
    agent_id = socketData.get("agent_id")
    if agent_id:
        logger.info(f"Saving agent_id {agent_id} to session for socket {sid}")
        await sio.save_session(sid, {"agent_id": agent_id})

    await handle_atlas_visitor_connected_service(socketData, sid)