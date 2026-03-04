from logging_config import get_logger
from services.elysium_atlas_services.atlas_redis_services import add_visitor_to_agent, get_visitors_for_agent, get_visitor_count_for_agent, remove_visitor_from_agent, add_team_member, add_agent_member, remove_team_member, remove_agent_member, get_or_cache_agent_data_async
from services.elysium_atlas_services.atlas_chat_session_services import set_visitor_online_status

logger = get_logger()

async def handle_visitor_connection(agent_id, chat_session_id, sid, geo_data=None, visitor_at=None):
    from sockets import sio
    room_name = f"agent_{agent_id}_visitors"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for chat_session_id {chat_session_id}")
    
    # Save agent_id and chat_session_id in session
    await sio.save_session(sid, {"agent_id": agent_id, "chat_session_id": chat_session_id})
    
    # Add visitor to Redis (returns the visitor data dict)
    visitor_data = add_visitor_to_agent(agent_id, chat_session_id, sid, geo_data=geo_data, visitor_at=visitor_at)

    # Mark visitor as online in the chat session document
    await set_visitor_online_status(agent_id, chat_session_id, True)

    # Broadcast new visitor to all team members connected to this agent
    agent_members_room = f"agent_{agent_id}_members"
    if visitor_data:
        visitor_count = get_visitor_count_for_agent(agent_id)
        await sio.emit(
            "agent_new_visitor",
            {
                "agent_id": agent_id,
                "visitor": visitor_data,
                "total": visitor_count if visitor_count is not None else 0
            },
            room=agent_members_room
        )
        logger.info(f"Emitted agent_new_visitor to room {agent_members_room} for agent {agent_id}, chat_session_id {chat_session_id}")

    # Emit updated visitor count to the agent's team room if agent data is cached/available
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
    await sio.save_session(sid, {"team_id": team_id, "user_id": user_id, "agent_id": agent_id})

    # Add team member to Redis (by team)
    add_team_member(team_id, user_id, agent_id, sid)

    # Emit visitor counts for all agents owned by this user (only when not scoped to a specific agent)
    if not agent_id:
        visitor_counts_data = await get_agents_visitor_counts_controller({"success": True, "user_id": user_id})
        await sio.emit("agents_visitor_counts", visitor_counts_data, to=sid)
        logger.info(f"Emitted agents_visitor_counts to socket {sid} for user_id {user_id}")

async def emit_agent_visitors_list(agent_id, sid, page=1, limit=100):
    """
    Fetch a paginated visitors list for the given agent from Redis and emit
    'agent_visitors_list' to the specified socket.

    Args:
        agent_id (str): The agent ID
        sid (str): Target socket ID
        page (int): Page number (1-based, default: 1)
        limit (int): Number of visitors per page (default: 100)
    """
    from sockets import sio
    visitors_data = get_visitors_for_agent(agent_id, page=page, size=limit)
    if visitors_data is not None:
        await sio.emit(
            "agent_visitors_list",
            {
                "agent_id": agent_id,
                "visitors": visitors_data["visitors"],
                "total": visitors_data["total"],
                "page": visitors_data["page"],
                "size": visitors_data["size"],
                "has_next": visitors_data["has_next"],
                "has_prev": visitors_data["has_prev"]
            },
            to=sid
        )
        logger.info(f"Emitted agent_visitors_list to socket {sid} for agent {agent_id}: {len(visitors_data['visitors'])} visitors (page {page}, limit {limit}, total {visitors_data['total']})")
    else:
        logger.warning(f"Could not retrieve visitors for agent {agent_id} to emit to socket {sid}")

async def handle_agent_member_connection(agent_id, team_id, user_id, sid, page=1, limit=100):
    from sockets import sio
    room_name = f"agent_{agent_id}_members"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for user_id {user_id}, team_id {team_id}")

    # Add agent member to Redis (by agent)
    add_agent_member(agent_id, team_id, user_id, sid)

    # Emit the latest visitors for this agent to the newly connected team member
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
    - Emits 'conversation_ended' to every visitor who was in conversation with this team member,
      and clears their in_conversation_with field in Redis.

    Args:
        socketData (dict): Payload containing team_id, user_id, and agent_id.
    """
    try:
        from sockets import sio
        from services.elysium_atlas_services.atlas_redis_services import (
            remove_team_members_by_user_id,
            remove_agent_members_by_user_id,
            get_visitors_in_conversation_with,
            update_visitor_conversation_status,
        )
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_conversation_ended

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

        # Emit conversation_ended to all visitors that were in conversation with this team member
        if agent_id and user_id:
            visitors = get_visitors_in_conversation_with(agent_id, user_id)
            for visitor in visitors:
                visitor_sid = visitor.get("sid")
                chat_session_id = visitor.get("chat_session_id")
                if visitor_sid and chat_session_id:
                    # Clear conversation status in Redis
                    update_visitor_conversation_status(agent_id, chat_session_id, None)
                    # Notify the visitor
                    await emit_conversation_ended(visitor_sid, agent_id, chat_session_id)
                    logger.info(f"Emitted conversation_ended to visitor {chat_session_id} (sid: {visitor_sid}) due to team member {user_id} explicit disconnect")

    except Exception as e:
        logger.error(f"Error handling team member explicit disconnect: {e}")


async def handle_team_member_disconnected_service(session, sid):
    """
    Common cleanup called on native socket disconnect for team members.

    Steps:
      1. Determine which agent_ids this user was serving — use agent_id from session
         if present, otherwise scan the team members hash to discover them (before removal).
      2. Remove the socket (sid) from the team Redis hash.
      3. For every discovered agent_id:
         a. Remove the socket from the agent members Redis hash.
         b. Find all visitors whose in_conversation_with matches this user_id.
         c. Clear in_conversation_with in Redis and emit 'conversation_ended' to each visitor.
    """
    try:
        from services.elysium_atlas_services.atlas_redis_services import (
            get_agent_ids_for_user_in_team,
            get_visitors_in_conversation_with,
            update_visitor_conversation_status,
        )
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_conversation_ended

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

        # For each agent: remove from agent hash, then end any open conversations
        for agent_id in agent_ids:
            logger.info(f"Removing team member socket {sid} from agent {agent_id} members")
            remove_agent_member(agent_id, sid)

            if user_id:
                visitors = get_visitors_in_conversation_with(agent_id, user_id)
                for visitor in visitors:
                    visitor_sid = visitor.get("sid")
                    chat_session_id = visitor.get("chat_session_id")
                    if visitor_sid and chat_session_id:
                        update_visitor_conversation_status(agent_id, chat_session_id, None)
                        await emit_conversation_ended(visitor_sid, agent_id, chat_session_id)
                        logger.info(
                            f"Emitted conversation_ended to visitor {chat_session_id} "
                            f"(sid: {visitor_sid}) because team member {user_id} (socket {sid}) disconnected"
                        )

    except Exception as e:
        logger.error(f"Error handling team member disconnection for sid {sid}: {e}")