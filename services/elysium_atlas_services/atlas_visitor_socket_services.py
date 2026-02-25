from logging_config import get_logger
from services.elysium_atlas_services.atlas_redis_services import add_visitor_to_agent, get_visitors_for_agent, get_visitor_count_for_agent, remove_visitor_from_agent, add_team_member, add_agent_member, remove_team_member, remove_agent_member, get_or_cache_agent_data_async
from services.elysium_atlas_services.atlas_chat_session_services import set_visitor_online_status

logger = get_logger()

async def handle_visitor_connection(agent_id, chat_session_id, sid):
    from sockets import sio
    room_name = f"agent_{agent_id}_visitors"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for chat_session_id {chat_session_id}")
    
    # Save agent_id and chat_session_id in session
    await sio.save_session(sid, {"agent_id": agent_id, "chat_session_id": chat_session_id})
    
    # Add visitor to Redis
    add_visitor_to_agent(agent_id, chat_session_id, sid)

    # Mark visitor as online in the chat session document
    await set_visitor_online_status(agent_id, chat_session_id, True)

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
        
        if agent_id and sid:
            await handle_visitor_connection(agent_id, chat_session_id, sid)

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

async def handle_agent_member_connection(agent_id, team_id, user_id, sid):
    from sockets import sio
    room_name = f"agent_{agent_id}_members"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for user_id {user_id}, team_id {team_id}")

    # Add agent member to Redis (by agent)
    add_agent_member(agent_id, team_id, user_id, sid)

async def handle_atlas_team_member_connected_service(socketData, sid=None):
    try:
        team_id = socketData.get("team_id")
        user_id = socketData.get("user_id")
        agent_id = socketData.get("agent_id")

        if team_id and sid:
            await handle_team_member_connection(team_id, user_id, agent_id, sid)

        if agent_id and sid:
            await handle_agent_member_connection(agent_id, team_id, user_id, sid)

    except Exception as e:
        logger.error(f"Error handling atlas team member connected: {e}")

async def handle_team_member_disconnected_service(session, sid):
    """
    Common cleanup function called on socket disconnect for team members.
    Removes the socket from both the team members hash and the agent members hash (if agent_id present).
    """
    try:
        team_id = session.get("team_id") if session else None
        agent_id = session.get("agent_id") if session else None

        if team_id:
            logger.info(f"Removing team member socket {sid} from team {team_id} members")
            remove_team_member(team_id, sid)

        if agent_id:
            logger.info(f"Removing team member socket {sid} from agent {agent_id} members")
            remove_agent_member(agent_id, sid)

    except Exception as e:
        logger.error(f"Error handling team member disconnection for sid {sid}: {e}")