from logging_config import get_logger
from services.elysium_atlas_services.atlas_redis_services import add_visitor_to_agent, get_visitor_count_for_agent, remove_visitor_from_agent, add_team_member, add_agent_member, remove_team_member, remove_agent_member, get_or_cache_agent_data_async, update_visitor_alias_by_chat_session, get_visitor_by_chat_session
from services.elysium_atlas_services.atlas_chat_session_services import (
    set_visitor_online_status,
    patch_chat_session,
    ensure_chat_session_for_visitor,
    count_chat_sessions_for_agent,
    get_paginated_chat_sessions_for_agent_list,
    search_paginated_chat_sessions_for_agent,
    get_chat_session_in_conversation_with,
)
from config.atlas_chat_config import clamp_chat_session_list_page_size, validate_chat_session_search_query
from services.socket_connection_helpers import merge_socket_session

logger = get_logger()


def get_online_visitor_total(agent_id: str) -> int:
    """Current count of online visitors in Redis (live presence only)."""
    count = get_visitor_count_for_agent(agent_id)
    return count if count is not None else 0


async def get_agent_chat_session_total(agent_id: str) -> int:
    """Total persisted chat sessions for an agent (used for visitors list pagination)."""
    return await count_chat_sessions_for_agent(agent_id)


async def emit_agent_visitors_pagination_updated(agent_id: str, total: int | None = None):
    """
    Notify agent members that the chat session list total changed.

    Clients should recompute total_pages from total and their active limit.
    """
    from sockets import sio

    if total is None:
        total = await get_agent_chat_session_total(agent_id)

    agent_members_room = f"agent_{agent_id}_members"
    await sio.emit(
        "agent_visitors_pagination_updated",
        {"agent_id": agent_id, "total": total},
        room=agent_members_room,
    )
    logger.info(
        f"Emitted agent_visitors_pagination_updated to room {agent_members_room} "
        f"for agent {agent_id}: total={total}"
    )


async def emit_agent_visitor_count_updated(agent_id: str, visitor_count: int | None = None) -> None:
    """Notify the team room that the online visitor count changed."""
    from sockets import sio

    agent_data = await get_or_cache_agent_data_async(agent_id)
    if not agent_data:
        return

    team_id = agent_data.get("team_id")
    if not team_id:
        return

    if visitor_count is None:
        visitor_count = get_visitor_count_for_agent(agent_id)
    visitor_count = visitor_count if visitor_count is not None else 0

    team_room = f"team_{team_id}_members"
    await sio.emit(
        "agent_visitor_count_updated",
        {"agent_id": agent_id, "visitor_count": visitor_count},
        room=team_room,
    )
    logger.info(
        f"Emitted agent_visitor_count_updated to room {team_room} "
        f"for agent {agent_id}: {visitor_count}"
    )


async def emit_agent_visitor_disconnected_event(
    agent_id: str,
    chat_session_id: str | None,
    sid: str,
):
    """
    Emit disconnect + pagination update for the chat sessions list.

    Disconnect removes the visitor from the online Redis hash immediately;
    pagination.total reflects the total persisted chat session count (unchanged).
    """
    from sockets import sio

    total = await get_agent_chat_session_total(agent_id)
    agent_members_room = f"agent_{agent_id}_members"
    await sio.emit(
        "agent_visitor_disconnected",
        {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "sid": sid,
            "pagination": {"total": total},
        },
        room=agent_members_room,
    )
    logger.info(
        f"Emitted agent_visitor_disconnected to room {agent_members_room} "
        f"for agent {agent_id}, chat_session_id {chat_session_id}, sid {sid}, total={total}"
    )


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
    online_before = get_visitor_count_for_agent(agent_id) or 0
    was_removed = remove_visitor_from_agent(agent_id, sid)

    if was_removed is None:
        return
    if not was_removed:
        logger.info(
            f"Skipped visitor disconnect presence for sid {sid} "
            f"(not in online hash for agent {agent_id})"
        )
        return

    still_online = get_visitor_by_chat_session(agent_id, chat_session_id)
    if not still_online:
        await set_visitor_online_status(agent_id, chat_session_id, False)

    online_after = get_visitor_count_for_agent(agent_id) or 0
    if online_after != online_before:
        await emit_agent_visitor_count_updated(agent_id, online_after)

    if not still_online:
        await emit_agent_visitor_disconnected_event(agent_id, chat_session_id, sid)


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

        # 2. Update Redis only if visitor is currently online in the hash
        updated_sid = update_visitor_alias_by_chat_session(agent_id, chat_session_id, alias_name)
        if not updated_sid:
            logger.info(
                f"Visitor {chat_session_id} not currently connected in Redis for agent {agent_id} — "
                f"skipping Redis update, alias persisted to MongoDB only"
            )

        # 3. Always notify the agent members room so the team dashboard updates live
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

    previous_live = (
        get_visitor_by_chat_session(agent_id, chat_session_id)
        if chat_session_id and agent_id
        else None
    )
    was_already_online_same_socket = (
        previous_live is not None and previous_live.get("sid") == sid
    )

    # Ensure a persisted session exists before marking online (chat sessions list)
    if chat_session_id and agent_id:
        await ensure_chat_session_for_visitor(
            agent_id,
            chat_session_id,
            visitor_at=visitor_at,
        )

    # Add visitor to Redis (returns the visitor data dict)
    visitor_data = add_visitor_to_agent(agent_id, chat_session_id, sid, geo_data=geo_data, visitor_at=visitor_at, alias_name=alias_name)

    # Restore persisted human takeover handler onto live Redis when visitor reconnects
    if chat_session_id and agent_id:
        stored_handler = await get_chat_session_in_conversation_with(agent_id, chat_session_id)
        if stored_handler:
            from services.elysium_atlas_services.atlas_redis_services import update_visitor_conversation_status
            from services.elysium_atlas_services.atlas_team_member_emit_services import emit_conversation_started

            update_visitor_conversation_status(agent_id, chat_session_id, stored_handler)
            await emit_conversation_started(sid, agent_id, chat_session_id, stored_handler)
            logger.info(
                f"Restored in_conversation_with={stored_handler} for reconnected visitor "
                f"{chat_session_id} on agent {agent_id}"
            )

    online_count_after = get_visitor_count_for_agent(agent_id) or 0

    # Presence signals only — never push agent_visitors_list (frontend refetches manually)
    if visitor_data and not was_already_online_same_socket:
        session_total = await get_agent_chat_session_total(agent_id)
        await emit_agent_visitors_pagination_updated(agent_id, total=session_total)
        await emit_agent_visitor_count_updated(agent_id, online_count_after)
    elif was_already_online_same_socket:
        logger.info(
            f"Skipped presence emits for duplicate atlas-visitor-connected: "
            f"chat_session_id={chat_session_id} sid={sid}"
        )

    # Mark visitor as online in the chat session document
    await set_visitor_online_status(agent_id, chat_session_id, True)

    # Persist geo_data to the chat session document if provided
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

async def handle_team_member_connection(team_id, user_id, agent_id, sid):
    from sockets import sio
    from controllers.elysium_atlas_controller_files.atlas_visitors_controllers import get_agents_visitor_counts_controller
    room_name = f"team_{team_id}_members"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for user_id {user_id}, agent_id {agent_id}")

    # Save team_id, user_id, and agent_id in session
    await merge_socket_session(sio, sid, {"team_id": team_id, "user_id": user_id, "agent_id": agent_id})

    # Add team member to Redis (by team)
    add_team_member(team_id, user_id, agent_id, sid)

    # Emit visitor counts for all agents owned by this user (only when not scoped to a specific agent)
    if not agent_id:
        visitor_counts_data = await get_agents_visitor_counts_controller({"success": True, "user_id": user_id})
        await sio.emit("agents_visitor_counts", visitor_counts_data, to=sid)
        logger.info(f"Emitted agents_visitor_counts to socket {sid} for user_id {user_id}")

async def emit_agent_visitors_list(agent_id, sid, page=1, limit=100):
    """
    Fetch a paginated chat sessions list for the agent and emit agent_visitors_list.

    Includes all persisted atlas_chat_sessions for the agent (not only online visitors),
    sorted by last_message_at descending. visitor_online reflects live Redis presence.
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


async def handle_agent_member_connection(agent_id, team_id, user_id, sid, page=1, limit=100):
    from sockets import sio
    room_name = f"agent_{agent_id}_members"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for user_id {user_id}, team_id {team_id}")

    add_agent_member(agent_id, team_id, user_id, sid)
    await merge_socket_session(sio, sid, {"visitors_list_limit": max(1, limit)})

    await emit_agent_visitors_list(agent_id, sid, page=page, limit=limit)

async def handle_atlas_team_member_connected_service(socketData, sid=None):
    try:
        team_id = socketData.get("team_id")
        user_id = socketData.get("user_id")
        agent_id = socketData.get("agent_id")
        page = socketData.get("page", 1)
        limit = socketData.get("limit", 100)

        if team_id and sid:
            await handle_team_member_connection(team_id, user_id, agent_id, sid)

        if agent_id and sid:
            await handle_agent_member_connection(agent_id, team_id, user_id, sid, page=page, limit=limit)

    except Exception as e:
        logger.error(f"Error handling atlas team member connected: {e}")

async def handle_team_member_explicit_disconnect_service(socketData):
    """
    Handle an explicit atlas-team-member-disconnected event.

    - Removes the team member from the team Redis hash and leaves the team room for all their sids.
    - Removes the team member from the agent Redis hash and leaves the agent members room for all their sids.
    - Clears passive monitor registrations for this user on the agent.

    Human takeover (in_conversation_with) is **not** released on disconnect — it persists in Mongo
    until the team member explicitly ends the conversation.
    """
    try:
        from sockets import sio
        from services.elysium_atlas_services.atlas_redis_services import (
            remove_team_members_by_user_id,
            remove_agent_members_by_user_id,
            remove_all_session_monitors_for_user,
        )

        team_id = socketData.get("team_id")
        user_id = socketData.get("user_id")
        agent_id = socketData.get("agent_id")

        # Remove from team Redis and leave the team room for all sids
        if team_id and user_id:
            team_sids = remove_team_members_by_user_id(team_id, user_id)
            team_room = f"team_{team_id}_members"
            for member_sid in team_sids:
                await sio.leave_room(member_sid, team_room)
                logger.info(f"Socket {member_sid} left room {team_room} (explicit disconnect for user_id {user_id})")

        # Remove from agent Redis and leave the agent members room for all sids
        if agent_id and user_id:
            agent_sids = remove_agent_members_by_user_id(agent_id, user_id)
            agent_members_room = f"agent_{agent_id}_members"
            for member_sid in agent_sids:
                await sio.leave_room(member_sid, agent_members_room)
                logger.info(f"Socket {member_sid} left room {agent_members_room} (explicit disconnect for user_id {user_id})")
            remove_all_session_monitors_for_user(agent_id, user_id)

    except Exception as e:
        logger.error(f"Error handling team member explicit disconnect: {e}")


async def handle_team_member_disconnected_service(session, sid):
    """
    Common cleanup called on native socket disconnect for team members.

    Steps:
      1. Determine which agent_ids this user was serving — use agent_id from session
         if present, otherwise scan the team members hash to discover them (before removal).
      2. Remove the socket (sid) from the team Redis hash.
      3. For every discovered agent_id: remove the socket from the agent members Redis hash
         and clear passive monitor registrations for this sid.

    Human takeover is **not** released on disconnect.
    """
    try:
        from services.elysium_atlas_services.atlas_redis_services import (
            get_agent_ids_for_user_in_team,
            remove_all_session_monitors_for_user,
        )

        team_id = session.get("team_id") if session else None
        user_id = session.get("user_id") if session else None
        session_agent_id = session.get("agent_id") if session else None

        # Collect agent_ids BEFORE removing from Redis so the scan is still valid
        agent_ids = []
        if session_agent_id:
            agent_ids = [session_agent_id]
        elif team_id and user_id:
            agent_ids = get_agent_ids_for_user_in_team(team_id, user_id)

        # Remove this sid from the team hash
        if team_id:
            logger.info(f"Removing team member socket {sid} from team {team_id} members")
            remove_team_member(team_id, sid)

        # For each agent: remove from agent hash and clear monitor registrations for this sid
        for agent_id in agent_ids:
            logger.info(f"Removing team member socket {sid} from agent {agent_id} members")
            remove_agent_member(agent_id, sid)

            if user_id:
                remove_all_session_monitors_for_user(agent_id, user_id, sid=sid)

    except Exception as e:
        logger.error(f"Error handling team member disconnection for sid {sid}: {e}")