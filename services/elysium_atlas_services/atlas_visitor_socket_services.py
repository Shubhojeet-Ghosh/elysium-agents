from logging_config import get_logger
from services.elysium_atlas_services.atlas_presence_services import (
    connect_visitor_presence,
    disconnect_visitor_presence,
    get_visitor_by_chat_session,
    get_visitor_count_for_agent,
    is_visitor_online,
    register_team_member_presence,
    set_team_member_offline,
    remove_team_member_presence,
    remove_team_member_active_agent,
    remove_session_monitors_for_user_on_agent,
)
from services.elysium_atlas_services.atlas_team_member_socket_rooms import enter_team_member_user_room
from services.elysium_atlas_services.atlas_visitor_socket_rooms import enter_visitor_session_room
from services.elysium_atlas_services.atlas_chat_session_services import (
    set_visitor_online_status,
    patch_chat_session,
    ensure_chat_session_for_visitor,
    get_paginated_chat_sessions_for_agent_list,
    search_paginated_chat_sessions_for_agent,
    get_chat_session_in_conversation_with,
    get_chat_sessions_by_ids_for_agent,
)
from config.atlas_chat_config import (
    clamp_chat_session_list_page_size,
    validate_chat_session_search_query,
    normalize_chat_session_refresh_ids,
)
from services.socket_connection_helpers import (
    merge_socket_session,
    resolve_socket_user_id,
    resolve_socket_team_id,
)

logger = get_logger()


async def get_online_visitor_total(agent_id: str) -> int:
    """Current count of online visitors for an agent (Mongo)."""
    return await get_visitor_count_for_agent(agent_id)


async def handle_visitor_socket_disconnect(
    agent_id: str,
    chat_session_id: str,
    sid: str,
) -> None:
    """
    Clean up visitor presence on socket disconnect.

    Skips presence emits when the sid was already replaced (widget reconnect).
    Does not mark visitor_online=false while another socket is still live for the session.
    """
    if not chat_session_id:
        return

    was_removed, _ = await disconnect_visitor_presence(agent_id, chat_session_id, sid)

    if not was_removed:
        logger.info(
            f"Skipped visitor disconnect presence for sid {sid} "
            f"(another socket still live for session {chat_session_id})"
        )


async def handle_set_visitor_alias_service(socketData, sid):
    """
    Set or update the alias_name for a visitor identified by agent_id + chat_session_id.

    Always writes to:
      - atlas_chat_sessions (MongoDB) — persistent, even if visitor is offline

    Only writes to Redis if the visitor is currently connected (present in the
    atlas_{agent_id}_visitors hash). Skipped silently if they are offline.

    Always emits 'agent_visitor_alias_updated' to the agent members room.

    Args:
        socketData (dict): Must contain agent_id, chat_session_id, alias_name.
        sid (str): Socket ID of the requesting team member.
    """
    try:
        from sockets import sio
        from services.mongo_services import get_collection

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")
        alias_name = socketData.get("alias_name")

        if not agent_id or not chat_session_id or alias_name is None:
            logger.warning("handle_set_visitor_alias_service: agent_id, chat_session_id and alias_name are required")
            return

        # 1. Always persist to MongoDB (visitor may be offline)
        collection = get_collection("atlas_chat_sessions")
        await collection.update_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"$set": {"alias_name": alias_name}}
        )
        logger.info(f"Updated alias_name in atlas_chat_sessions for chat_session_id {chat_session_id}, agent_id {agent_id}")

        # Alias is persisted on atlas_chat_sessions only (no Redis overlay)
        agent_members_room = f"agent_{agent_id}_members"
        await sio.emit(
            "agent_visitor_alias_updated",
            {"agent_id": agent_id, "chat_session_id": chat_session_id, "alias_name": alias_name},
            room=agent_members_room
        )
        logger.info(f"Emitted agent_visitor_alias_updated to room {agent_members_room} for chat_session_id {chat_session_id}")

    except Exception as e:
        logger.error(f"Error in handle_set_visitor_alias_service: {e}")


async def _fetch_visitor_alias(agent_id, chat_session_id) -> str | None:
    """
    Fetch the persisted alias_name for a visitor from atlas_chat_sessions.

    Returns the stored alias_name string, or None if not set / not found.
    """
    try:
        from services.mongo_services import get_collection
        collection = get_collection("atlas_chat_sessions")
        doc = await collection.find_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"alias_name": 1, "_id": 0}
        )
        return doc.get("alias_name") if doc else None
    except Exception as e:
        logger.warning(f"Could not fetch alias_name for {chat_session_id}: {e}")
        return None


async def handle_visitor_connection(agent_id, chat_session_id, sid, geo_data=None, visitor_at=None):
    from sockets import sio
    room_name = f"agent_{agent_id}_visitors"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for chat_session_id {chat_session_id}")

    # Save agent_id and chat_session_id in session
    await merge_socket_session(sio, sid, {"agent_id": agent_id, "chat_session_id": chat_session_id})

    # Fetch existing alias_name so reconnects don't reset it to None
    alias_name = await _fetch_visitor_alias(agent_id, chat_session_id) if (chat_session_id and agent_id) else None

    if chat_session_id:
        await enter_visitor_session_room(sid, chat_session_id)

    previous_online = (
        await is_visitor_online(agent_id, chat_session_id)
        if chat_session_id and agent_id
        else False
    )

    # Ensure a persisted session exists before marking online (chat sessions list)
    if chat_session_id and agent_id:
        await ensure_chat_session_for_visitor(
            agent_id,
            chat_session_id,
            visitor_at=visitor_at,
        )

    visitor_data = await connect_visitor_presence(
        agent_id,
        chat_session_id,
        geo_data=geo_data,
        visitor_at=visitor_at,
        alias_name=alias_name,
    )

    if chat_session_id and agent_id:
        stored_handler = await get_chat_session_in_conversation_with(agent_id, chat_session_id)
        if stored_handler:
            from services.elysium_atlas_services.atlas_presence_services import (
                update_visitor_conversation_status,
            )
            from services.elysium_atlas_services.atlas_team_member_emit_services import emit_conversation_started

            await update_visitor_conversation_status(agent_id, chat_session_id, stored_handler)
            await emit_conversation_started(agent_id, chat_session_id, stored_handler)
            logger.info(
                f"Restored in_conversation_with={stored_handler} for reconnected visitor "
                f"{chat_session_id} on agent {agent_id}"
            )
        else:
            from services.elysium_atlas_services.human_handover_services import (
                maybe_emit_pending_handover_on_visitor_connect,
            )

            await maybe_emit_pending_handover_on_visitor_connect(agent_id, chat_session_id)

    if visitor_data and not previous_online:
        logger.info(
            f"New visitor session online agent_id={agent_id} "
            f"chat_session_id={chat_session_id} sid={sid}"
        )
    elif previous_online:
        logger.info(
            f"Skipped duplicate atlas-visitor-connected: "
            f"chat_session_id={chat_session_id} sid={sid}"
        )

    # connect_visitor_presence sets visitor_online on the session document
    if geo_data and chat_session_id and agent_id:
        await patch_chat_session(agent_id, chat_session_id, {"geo_data": geo_data})

async def handle_atlas_visitor_connected_service(socketData, sid=None):
    try:
        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")
        geo_data = socketData.get("geo_data")
        visitor_at = socketData.get("visitor_at")
        
        if agent_id and sid:
            await handle_visitor_connection(agent_id, chat_session_id, sid, geo_data=geo_data, visitor_at=visitor_at)

    except Exception as e:
        logger.error(f"Error handling atlas visitor connected: {e}")

async def handle_team_member_connection(team_id, user_id, agent_id, sid, session: dict | None = None):
    from sockets import sio

    room_name = f"team_{team_id}_members"
    await sio.enter_room(sid, room_name)
    await merge_socket_session(
        sio,
        sid,
        {"team_id": team_id, "user_id": user_id, "agent_id": agent_id},
    )
    await enter_team_member_user_room(sid, user_id)
    await register_team_member_presence(team_id, user_id)

async def emit_agent_visitors_list(agent_id, sid, page=1, limit=100):
    """
    Fetch a paginated chat sessions list for the agent and emit agent_visitors_list.

    Includes all persisted atlas_chat_sessions for the agent (not only online visitors),
    sorted by last_message_at descending. visitor_online reflects Mongo session presence.
    Out-of-range pages are clamped to the last valid page when sessions exist.
    """
    from sockets import sio

    page = max(1, page)
    limit = clamp_chat_session_list_page_size(limit)
    await merge_socket_session(sio, sid, {"visitors_list_limit": limit})

    visitors_data = await get_paginated_chat_sessions_for_agent_list(agent_id, page=page, size=limit)
    if visitors_data is not None:
        await sio.emit(
            "agent_visitors_list",
            {
                "agent_id": agent_id,
                "visitors": visitors_data["visitors"],
                "total": visitors_data["total"],
                "page": visitors_data["page"],
                "size": visitors_data["size"],
                "total_pages": visitors_data["total_pages"],
                "has_next": visitors_data["has_next"],
                "has_prev": visitors_data["has_prev"],
            },
            to=sid
        )
        logger.info(
            f"Emitted agent_visitors_list to socket {sid} for agent {agent_id}: "
            f"{len(visitors_data['visitors'])} session(s) "
            f"(page {visitors_data['page']}, limit {limit}, total {visitors_data['total']})"
        )
    else:
        logger.warning(f"Could not retrieve visitors for agent {agent_id} to emit to socket {sid}")


async def emit_agent_visitors_search_results(
    agent_id: str,
    sid: str,
    query: str,
    page: int = 1,
    limit: int = 100,
) -> None:
    """
    Run a paginated chat session search and emit agent_visitors_search_results to the requester.

    Matches substrings on chat_session_id or alias_name (case-insensitive).
    """
    from sockets import sio

    page = max(1, page)
    limit = clamp_chat_session_list_page_size(limit)

    is_valid, error_message, _ = validate_chat_session_search_query(query)
    if not agent_id:
        await sio.emit(
            "agent_visitors_search_results",
            {
                "success": False,
                "message": "agent_id is required.",
                "agent_id": agent_id,
                "query": (query or "").strip() if isinstance(query, str) else "",
                "visitors": [],
                "total": 0,
                "page": 1,
                "size": limit,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            },
            to=sid,
        )
        return

    if not is_valid:
        await sio.emit(
            "agent_visitors_search_results",
            {
                "success": False,
                "message": error_message,
                "agent_id": agent_id,
                "query": (query or "").strip() if isinstance(query, str) else "",
                "visitors": [],
                "total": 0,
                "page": 1,
                "size": limit,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            },
            to=sid,
        )
        logger.warning(
            f"Invalid chat session search from socket {sid} for agent {agent_id}: {error_message}"
        )
        return

    search_data = await search_paginated_chat_sessions_for_agent(
        agent_id,
        query,
        page=page,
        size=limit,
    )
    if search_data is None:
        await sio.emit(
            "agent_visitors_search_results",
            {
                "success": False,
                "message": "Failed to search chat sessions.",
                "agent_id": agent_id,
                "query": query.strip(),
                "visitors": [],
                "total": 0,
                "page": 1,
                "size": limit,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            },
            to=sid,
        )
        logger.warning(f"Could not search visitors for agent {agent_id} to emit to socket {sid}")
        return

    await sio.emit(
        "agent_visitors_search_results",
        {
            "success": search_data.get("success", True),
            "message": search_data.get("message"),
            "agent_id": agent_id,
            "query": search_data.get("query", query.strip()),
            "visitors": search_data["visitors"],
            "total": search_data["total"],
            "page": search_data["page"],
            "size": search_data["size"],
            "total_pages": search_data["total_pages"],
            "has_next": search_data["has_next"],
            "has_prev": search_data["has_prev"],
        },
        to=sid,
    )
    logger.info(
        f"Emitted agent_visitors_search_results to socket {sid} for agent {agent_id}: "
        f"query={search_data.get('query')!r} "
        f"{len(search_data['visitors'])} session(s) "
        f"(page {search_data['page']}, limit {limit}, total {search_data['total']})"
    )


async def emit_agent_visitors_sessions_refresh(
    agent_id: str,
    sid: str,
    chat_session_ids: list[str] | None,
    session: dict | None = None,
) -> None:
    """
    Return fresh list rows for the visible chat sessions on the requester's dashboard.

    Emits agent_visitors_sessions_refreshed only to the requesting socket (no room fan-out).
    """
    from sockets import sio
    from services.elysium_atlas_services.team_auth_services import can_user_read_agent

    async def _emit_error(message: str) -> None:
        await sio.emit(
            "agent_visitors_sessions_refreshed",
            {
                "success": False,
                "message": message,
                "agent_id": agent_id,
                "visitors": [],
            },
            to=sid,
        )

    if not agent_id:
        await _emit_error("agent_id is required.")
        return

    user_id = resolve_socket_user_id(session)
    if not user_id:
        await _emit_error("Authenticated user_id is required.")
        return

    if not await can_user_read_agent(user_id, agent_id):
        await _emit_error("You are not authorized to access this agent.")
        return

    is_valid, error_message, normalized_ids = normalize_chat_session_refresh_ids(chat_session_ids)
    if not is_valid:
        await _emit_error(error_message or "Invalid chat_session_ids.")
        logger.warning(
            f"Invalid visible-session refresh from socket {sid} for agent {agent_id}: "
            f"{error_message}"
        )
        return

    visitors = await get_chat_sessions_by_ids_for_agent(agent_id, normalized_ids)
    if visitors is None:
        await _emit_error("Failed to refresh chat sessions.")
        return

    await sio.emit(
        "agent_visitors_sessions_refreshed",
        {
            "success": True,
            "message": None,
            "agent_id": agent_id,
            "visitors": visitors,
        },
        to=sid,
    )
    logger.info(
        f"Emitted agent_visitors_sessions_refreshed to socket {sid} for agent {agent_id}: "
        f"{len(visitors)} session(s) requested={len(normalized_ids)}"
    )


async def handle_agent_member_connection(agent_id, team_id, user_id, sid, page=1, limit=100):
    from sockets import sio
    room_name = f"agent_{agent_id}_members"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for user_id {user_id}, team_id {team_id}")

    await enter_team_member_user_room(sid, user_id)
    await register_team_member_presence(team_id, user_id, agent_id=agent_id)
    await merge_socket_session(sio, sid, {"visitors_list_limit": max(1, limit)})

    await emit_agent_visitors_list(agent_id, sid, page=page, limit=limit)

async def handle_atlas_team_member_connected_service(socketData, sid=None, session: dict | None = None):
    try:
        user_id = socketData.get("user_id") or resolve_socket_user_id(session)
        team_id = socketData.get("team_id") or resolve_socket_team_id(session)
        agent_id = socketData.get("agent_id")
        page = socketData.get("page", 1)
        limit = socketData.get("limit", 100)

        if team_id and sid and user_id:
            await handle_team_member_connection(team_id, user_id, agent_id, sid, session=session)

        if agent_id and sid:
            await handle_agent_member_connection(
                agent_id, team_id, user_id, sid, page=page, limit=limit
            )

    except Exception as e:
        logger.error(f"Error handling atlas team member connected: {e}")

async def handle_team_member_explicit_disconnect_service(socketData, sid: str | None = None):
    """
    Handle an explicit atlas-team-member-disconnected event.

    Updates Mongo presence and leaves Socket.IO rooms for the requesting socket.
    Clears passive monitor registrations for this user on the agent when applicable.
    """
    try:
        from sockets import sio
        from services.elysium_atlas_services.atlas_redis_services import (
            remove_all_session_monitors_for_user,
        )

        team_id = socketData.get("team_id")
        user_id = socketData.get("user_id")
        agent_id = socketData.get("agent_id")

        if agent_id and user_id and team_id:
            await remove_team_member_active_agent(team_id, user_id, agent_id)
            if sid:
                agent_members_room = f"agent_{agent_id}_members"
                await sio.leave_room(sid, agent_members_room)
                logger.info(
                    f"Socket {sid} left room {agent_members_room} "
                    f"(explicit agent disconnect for user_id {user_id})"
                )
            remove_all_session_monitors_for_user(agent_id, user_id)
        elif team_id and user_id:
            await remove_team_member_presence(team_id, user_id)
            if sid:
                team_room = f"team_{team_id}_members"
                await sio.leave_room(sid, team_room)
                logger.info(
                    f"Socket {sid} left room {team_room} "
                    f"(explicit team disconnect for user_id {user_id})"
                )

    except Exception as e:
        logger.error(f"Error handling team member explicit disconnect: {e}")


async def handle_team_member_disconnected_service(session, sid):
    """
    Native socket disconnect for team members: mark Mongo presence offline and
    clear passive session-monitor registrations. Human takeover is not released.
    """
    try:
        from services.elysium_atlas_services.atlas_redis_services import (
            remove_all_session_monitors_for_user,
        )
        from services.socket_connection_helpers import (
            resolve_socket_team_id,
            resolve_socket_user_id,
        )

        team_id = resolve_socket_team_id(session)
        user_id = resolve_socket_user_id(session)
        session_agent_id = session.get("agent_id") if session else None

        agent_ids: list[str] = []
        if user_id:
            logger.info(f"Updating team member presence after disconnect for user {user_id}")
            agent_ids = await set_team_member_offline(team_id, user_id)

        if session_agent_id and session_agent_id not in agent_ids:
            agent_ids.append(session_agent_id)

        for agent_id in agent_ids:
            if user_id:
                remove_all_session_monitors_for_user(agent_id, user_id, sid=sid)

    except Exception as e:
        logger.error(f"Error handling team member disconnection for sid {sid}: {e}")