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
from controllers.elysium_atlas_controller_files.atlas_team_member_chat_controllers import (
    chat_with_visitor_controller_v1,
    team_member_start_conversation_controller,
    team_member_end_conversation_controller,
    team_member_monitor_conversation_controller,
    team_member_stop_monitor_conversation_controller,
    team_member_resolve_session_controller,
)
from services.socket_connection_helpers import (
    add_socket_connection,
    remove_socket_connection,
    add_user_socket_mapping,
    remove_user_socket_mapping,
    get_user_id_from_user_data,
    merge_socket_session,
    resolve_socket_user_id,
    resolve_socket_team_id,
)
from services.elysium_atlas_services.atlas_visitor_socket_services import (
    handle_atlas_visitor_connected_service,
    handle_atlas_team_member_connected_service,
    handle_team_member_disconnected_service,
    handle_team_member_explicit_disconnect_service,
    emit_agent_visitors_list,
    emit_agent_visitors_search_results,
    emit_agent_visitors_sessions_refresh,
    handle_set_visitor_alias_service,
    handle_visitor_socket_disconnect,
)

logger = get_logger()

REDIS_URL = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"

mgr = AsyncRedisManager(REDIS_URL, write_only=True, channel="socketio")

sio = socketio.AsyncServer(
    cors_allowed_origins="*",
    async_mode="asgi",
    client_manager=mgr,
    ping_interval=25,
    ping_timeout=60,
)

socketio_app = socketio.ASGIApp(sio)


async def _socket_session(sid: str) -> dict:
    try:
        session = await sio.get_session(sid)
        return session if isinstance(session, dict) else {}
    except KeyError:
        return {}


@sio.on("connect")
async def connect(sid, environ, auth):
    try:
        add_socket_connection(sid)
        user_data = extract_token_from_socket_environ(environ, auth)
        if not user_data:
            return

        session_updates: dict = {"user_data": user_data}
        user_id = get_user_id_from_user_data(user_data)
        if user_id:
            session_updates["user_id"] = user_id
        team_id = user_data.get("team_id")
        if team_id:
            session_updates["team_id"] = str(team_id).strip()
        await merge_socket_session(sio, sid, session_updates)
        if user_id:
            from services.elysium_atlas_services.atlas_team_member_socket_rooms import (
                enter_team_member_user_room,
            )
            await enter_team_member_user_room(sid, user_id)
        add_user_socket_mapping(user_data, sid)
    except Exception as e:
        logger.error(f"Error on socket connect {sid}: {e}")


@sio.on("disconnect")
async def disconnect(sid, reason=None):
    try:
        session = await _socket_session(sid)
        user_data = session.get("user_data")
        if user_data:
            user_id = get_user_id_from_user_data(user_data)
            if user_id:
                remove_user_socket_mapping(user_id, sid)

        agent_id = session.get("agent_id")
        chat_session_id = session.get("chat_session_id")
        if agent_id and chat_session_id:
            await handle_visitor_socket_disconnect(agent_id, chat_session_id, sid)

        if resolve_socket_user_id(session):
            await handle_team_member_disconnected_service(session, sid)

        remove_socket_connection(sid)
    except Exception as e:
        logger.error(f"Error on socket disconnect {sid}: {e}")


@sio.on("atlas-visitor-connected")
async def handle_atlas_visitor_connected(sid, socketData):
    agent_id = socketData.get("agent_id")
    chat_session_id = socketData.get("chat_session_id")
    if agent_id:
        await merge_socket_session(sio, sid, {"agent_id": agent_id, "chat_session_id": chat_session_id})
    await handle_atlas_visitor_connected_service(socketData, sid)


@sio.on("atlas-visitor-message")
async def handle_atlas_visitor_message(sid, socketData):
    if isinstance(socketData, dict):
        socketData["_request_started_at"] = time.perf_counter()
        socketData["_message_received_at"] = datetime.datetime.now(datetime.timezone.utc)
    await chat_with_agent_controller_v1(socketData, None, sid)


@sio.on("atlas-team-member-connected")
async def handle_atlas_team_member_connected(sid, socketData):
    session = await _socket_session(sid)
    await handle_atlas_team_member_connected_service(socketData, sid, session=session)


@sio.on("atlas-agent-visitors-list")
async def handle_atlas_agent_visitors_list(sid, socketData):
    agent_id = socketData.get("agent_id")
    if not agent_id:
        return
    await emit_agent_visitors_list(
        agent_id, sid, page=socketData.get("page", 1), limit=socketData.get("limit", 100)
    )


@sio.on("atlas-agent-visitors-search")
async def handle_atlas_agent_visitors_search(sid, socketData):
    await emit_agent_visitors_search_results(
        socketData.get("agent_id"),
        sid,
        socketData.get("query"),
        page=socketData.get("page", 1),
        limit=socketData.get("limit", 100),
    )


@sio.on("atlas-agent-visitors-refresh-sessions")
async def handle_atlas_agent_visitors_refresh_sessions(sid, socketData):
    session = await _socket_session(sid)
    if not isinstance(socketData, dict):
        socketData = {}
    await emit_agent_visitors_sessions_refresh(
        socketData.get("agent_id"),
        sid,
        socketData.get("chat_session_ids"),
        session=session,
    )


@sio.on("atlas-team-member-message")
async def handle_atlas_team_member_message(sid, socketData):
    if isinstance(socketData, dict):
        socketData["_message_received_at"] = datetime.datetime.now(datetime.timezone.utc)
    session = await _socket_session(sid)
    await chat_with_visitor_controller_v1(sid, socketData, session=session)


@sio.on("atlas-team-member-start-conversation")
async def handle_atlas_team_member_start_conversation(sid, socketData):
    session = await _socket_session(sid)
    await team_member_start_conversation_controller(sid, socketData, session=session)


@sio.on("atlas-team-member-monitor-conversation")
async def handle_atlas_team_member_monitor_conversation(sid, socketData):
    session = await _socket_session(sid)
    await team_member_monitor_conversation_controller(sid, socketData, session=session)


@sio.on("atlas-team-member-stop-monitor-conversation")
async def handle_atlas_team_member_stop_monitor_conversation(sid, socketData):
    session = await _socket_session(sid)
    await team_member_stop_monitor_conversation_controller(sid, socketData, session=session)


@sio.on("atlas-team-member-end-conversation")
async def handle_atlas_team_member_end_conversation(sid, socketData):
    session = await _socket_session(sid)
    await team_member_end_conversation_controller(sid, socketData, session=session)


@sio.on("atlas-team-member-resolve-session")
async def handle_atlas_team_member_resolve_session(sid, socketData):
    session = await _socket_session(sid)
    await team_member_resolve_session_controller(sid, socketData, session=session)


@sio.on("atlas-team-member-disconnected")
async def handle_atlas_team_member_disconnected(sid, socketData):
    await handle_team_member_explicit_disconnect_service(socketData, sid=sid)


@sio.on("atlas-set-visitor-alias")
async def handle_atlas_set_visitor_alias(sid, socketData):
    await handle_set_visitor_alias_service(socketData, sid)
