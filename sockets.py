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
from services.elysium_atlas_services.atlas_visitor_socket_services import handle_atlas_visitor_connected_service, handle_atlas_team_member_connected_service, handle_team_member_disconnected_service, emit_agent_visitors_list

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
        chat_session_id = session.get("chat_session_id") if session else None
        if agent_id:
            logger.info(f"Removing visitor socket {sid} from agent {agent_id} visitors")
            from services.elysium_atlas_services.atlas_redis_services import remove_visitor_from_agent, get_visitor_count_for_agent, get_or_cache_agent_data_async
            from services.elysium_atlas_services.atlas_chat_session_services import set_visitor_online_status
            remove_visitor_from_agent(agent_id, sid)
            if chat_session_id:
                await set_visitor_online_status(agent_id, chat_session_id, False)

            # Emit updated visitor count to the agent's team room
            # and notify agent members of the specific visitor that disconnected
            agent_data = await get_or_cache_agent_data_async(agent_id)
            if agent_data:
                team_id = agent_data.get("team_id")
                if team_id:
                    visitor_count = get_visitor_count_for_agent(agent_id)
                    team_room = f"team_{team_id}_members"
                    await sio.emit(
                        "agent_visitor_count_updated",
                        {"agent_id": agent_id, "visitor_count": visitor_count if visitor_count is not None else 0},
                        room=team_room
                    )
                    logger.info(f"Emitted agent_visitor_count_updated to room {team_room} for agent {agent_id}: {visitor_count}")

            # Notify team members scoped to this agent that a specific visitor disconnected
            agent_members_room = f"agent_{agent_id}_members"
            await sio.emit(
                "agent_visitor_disconnected",
                {"agent_id": agent_id, "chat_session_id": chat_session_id, "sid": sid},
                room=agent_members_room
            )
            logger.info(f"Emitted agent_visitor_disconnected to room {agent_members_room} for agent {agent_id}, chat_session_id {chat_session_id}, sid {sid}")

        # Check if it's a team member and remove from team/agent Redis
        team_id = session.get("team_id") if session else None
        if team_id:
            await handle_team_member_disconnected_service(session, sid)
        
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
    
    # Save agent_id and chat_session_id to session for disconnect handling
    agent_id = socketData.get("agent_id")
    chat_session_id = socketData.get("chat_session_id")
    if agent_id:
        logger.info(f"Saving agent_id {agent_id} and chat_session_id {chat_session_id} to session for socket {sid}")
        await sio.save_session(sid, {"agent_id": agent_id, "chat_session_id": chat_session_id})

    await handle_atlas_visitor_connected_service(socketData, sid)

# Handle 'atlas-team-member-connected' event
@sio.on("atlas-team-member-connected")
async def handle_atlas_team_member_connected(sid, socketData):
    team_id = socketData.get("team_id")
    user_id = socketData.get("user_id")
    agent_id = socketData.get("agent_id")

    logger.info(f"Saving team_id {team_id}, user_id {user_id}, and agent_id {agent_id} to session for socket {sid}")
    await sio.save_session(sid, {"team_id": team_id, "user_id": user_id, "agent_id": agent_id})

    await handle_atlas_team_member_connected_service(socketData, sid)

# Handle 'atlas-agent-visitors-list' event - fetch paginated visitors for an agent
@sio.on("atlas-agent-visitors-list")
async def handle_atlas_agent_visitors_list(sid, socketData):
    try:
        agent_id = socketData.get("agent_id")
        page = socketData.get("page", 1)
        limit = socketData.get("limit", 100)

        if not agent_id:
            logger.warning(f"atlas-agent-visitors-list received without agent_id from socket {sid}")
            return

        logger.info(f"Event 'atlas-agent-visitors-list' received from socket {sid} for agent {agent_id} (page {page}, limit {limit})")
        await emit_agent_visitors_list(agent_id, sid, page=page, limit=limit)
    except Exception as e:
        logger.error(f"Error handling atlas-agent-visitors-list for socket {sid}: {e}")