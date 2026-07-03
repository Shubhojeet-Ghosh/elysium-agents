"""
Socket.IO configuration and event handlers
"""

import time
import datetime
import socketio
from socketio import AsyncRedisManager

from logging_config import get_logger
from config.settings import settings
from middlewares.socket_auth import extract_token_from_socket_environ
from controllers.elysium_atlas_controller_files.atlas_chat_controllers import chat_with_agent_controller_v1
from controllers.elysium_atlas_controller_files.atlas_team_member_chat_controllers import chat_with_visitor_controller_v1, team_member_start_conversation_controller, team_member_end_conversation_controller, team_member_monitor_conversation_controller, team_member_stop_monitor_conversation_controller, team_member_resolve_session_controller

from services.socket_connection_helpers import (
    add_socket_connection,
    remove_socket_connection,
    add_user_socket_mapping,
    remove_user_socket_mapping,
    get_user_id_from_user_data,
    merge_socket_session,
)
from services.elysium_atlas_services.atlas_visitor_socket_services import handle_atlas_visitor_connected_service, handle_atlas_team_member_connected_service, handle_team_member_disconnected_service, handle_team_member_explicit_disconnect_service, emit_agent_visitors_list, emit_agent_visitors_search_results, handle_set_visitor_alias_service, handle_visitor_socket_disconnect

logger = get_logger()

REDIS_URL = f'redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}'

# Create a Redis manager (edit the URL if your Redis is elsewhere)
# write_only=True: emit only via Redis pub/sub so each client receives one copy
# (write_only=False emits locally AND via pub/sub, duplicating every room broadcast).
mgr = AsyncRedisManager(
    REDIS_URL,
    write_only=True,
    channel="socketio",
)

# Create Socket.IO instance
sio = socketio.AsyncServer(
    cors_allowed_origins="*",
    async_mode="asgi",
    client_manager=mgr,
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

        if user_data:
            session_updates: dict = {"user_data": user_data}
            user_id = get_user_id_from_user_data(user_data)
            if user_id:
                session_updates["user_id"] = user_id
            team_id = user_data.get("team_id")
            if team_id:
                session_updates["team_id"] = str(team_id).strip()
            await merge_socket_session(sio, sid, session_updates)

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
async def disconnect(sid, reason=None):
    try:
        logger.info(f"Disconnect event for sid {sid}. Reason: {reason}")
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
        
        # Visitor disconnect only — team members also store agent_id on the session
        agent_id = session.get("agent_id") if session else None
        chat_session_id = session.get("chat_session_id") if session else None
        if agent_id and chat_session_id:
            logger.info(f"Removing visitor socket {sid} from agent {agent_id} visitors")
            await handle_visitor_socket_disconnect(agent_id, chat_session_id, sid)

        # Check if it's a team member and remove from team/agent Redis
        team_id = session.get("team_id") if session else None
        if team_id:
            await handle_team_member_disconnected_service(session, sid)
        
        remove_socket_connection(sid)
        logger.info(f"Client disconnected: {sid}.")
    except Exception as e:
        logger.error(f"Error removing socket connection {sid}: {e}")

# Handle 'atlas-visitor-connected' event
@sio.on("atlas-visitor-connected")
async def handle_atlas_visitor_connected(sid, socketData):
    
    # Save agent_id and chat_session_id to session for disconnect handling
    agent_id = socketData.get("agent_id")
    chat_session_id = socketData.get("chat_session_id")
    if agent_id:
        logger.info(f"Saving agent_id {agent_id} and chat_session_id {chat_session_id} to session for socket {sid}")
        await merge_socket_session(sio, sid, {"agent_id": agent_id, "chat_session_id": chat_session_id})

    await handle_atlas_visitor_connected_service(socketData, sid)

# Handle 'atlas-visitor-message' event - main chat orchestrator for atlas users
@sio.on("atlas-visitor-message")
async def handle_atlas_visitor_message(sid,socketData):
    request_started_at = time.perf_counter()
    if isinstance(socketData, dict):
        socketData["_request_started_at"] = request_started_at
        socketData["_message_received_at"] = datetime.datetime.now(datetime.timezone.utc)
    logger.info("Event 'atlas-visitor-message' received")
    session = await sio.get_session(sid)
    user_data = session.get("user_data") if session else None
    logger.info(user_data)

    response = await chat_with_agent_controller_v1(socketData, user_data, sid)

# Handle 'atlas-team-member-connected' event
@sio.on("atlas-team-member-connected")
async def handle_atlas_team_member_connected(sid, socketData):
    team_id = socketData.get("team_id")
    user_id = socketData.get("user_id")
    agent_id = socketData.get("agent_id")

    logger.info(f"Saving team_id {team_id}, user_id {user_id}, and agent_id {agent_id} to session for socket {sid}")
    await merge_socket_session(sio, sid, {"team_id": team_id, "user_id": user_id, "agent_id": agent_id})

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

# Handle 'atlas-agent-visitors-search' event - search paginated chat sessions for an agent
@sio.on("atlas-agent-visitors-search")
async def handle_atlas_agent_visitors_search(sid, socketData):
    try:
        agent_id = socketData.get("agent_id")
        query = socketData.get("query")
        page = socketData.get("page", 1)
        limit = socketData.get("limit", 100)

        logger.info(
            f"Event 'atlas-agent-visitors-search' received from socket {sid} "
            f"for agent {agent_id} (query={query!r}, page {page}, limit {limit})"
        )
        await emit_agent_visitors_search_results(agent_id, sid, query, page=page, limit=limit)
    except Exception as e:
        logger.error(f"Error handling atlas-agent-visitors-search for socket {sid}: {e}")

# Handle 'atlas-team-member-message' event - message from team member
@sio.on("atlas-team-member-message")
async def handle_atlas_team_member_message(sid, socketData):
    if isinstance(socketData, dict):
        socketData["_message_received_at"] = datetime.datetime.now(datetime.timezone.utc)
    await chat_with_visitor_controller_v1(sid, socketData)

# Handle 'atlas-team-member-start-conversation' event - team member starts a conversation with a visitor
@sio.on("atlas-team-member-start-conversation")
async def handle_atlas_team_member_start_conversation(sid, socketData):
    await team_member_start_conversation_controller(sid, socketData)

# Handle 'atlas-team-member-monitor-conversation' event - team member passively monitors visitor ↔ AI chat
@sio.on("atlas-team-member-monitor-conversation")
async def handle_atlas_team_member_monitor_conversation(sid, socketData):
    await team_member_monitor_conversation_controller(sid, socketData)

# Handle 'atlas-team-member-stop-monitor-conversation' event - team member stops passive monitoring
@sio.on("atlas-team-member-stop-monitor-conversation")
async def handle_atlas_team_member_stop_monitor_conversation(sid, socketData):
    await team_member_stop_monitor_conversation_controller(sid, socketData)

# Handle 'atlas-team-member-end-conversation' event - team member ends a conversation with a visitor
@sio.on("atlas-team-member-end-conversation")
async def handle_atlas_team_member_end_conversation(sid, socketData):
    await team_member_end_conversation_controller(sid, socketData)

# Handle 'atlas-team-member-resolve-session' event - team member marks a chat session as resolved
@sio.on("atlas-team-member-resolve-session")
async def handle_atlas_team_member_resolve_session(sid, socketData):
    await team_member_resolve_session_controller(sid, socketData)

# Handle 'atlas-team-member-disconnected' event - explicit team member logout/disconnect
@sio.on("atlas-team-member-disconnected")
async def handle_atlas_team_member_disconnected(sid, socketData):
    logger.info(f"Event 'atlas-team-member-disconnected' received from socket {sid}")
    await handle_team_member_explicit_disconnect_service(socketData)

# Handle 'atlas-set-visitor-alias' event - team member sets alias for a visitor
@sio.on("atlas-set-visitor-alias")
async def handle_atlas_set_visitor_alias(sid, socketData):
    logger.info(f"Event 'atlas-set-visitor-alias' received from socket {sid}")
    await handle_set_visitor_alias_service(socketData, sid)