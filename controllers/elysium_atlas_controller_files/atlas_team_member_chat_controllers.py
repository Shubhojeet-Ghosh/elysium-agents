from logging_config import get_logger

logger = get_logger()

async def chat_with_visitor_controller_v1(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import get_visitor_sid_by_chat_session
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_visitor_message
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")
        message = socketData.get("message")

        # Get the team member's user_id from their socket session
        session = await sio.get_session(sid)
        in_conversation_with = session.get("user_id") if session else None

        visitor_sid = get_visitor_sid_by_chat_session(agent_id, chat_session_id)
        if visitor_sid:
            await emit_visitor_message(visitor_sid, agent_id, chat_session_id, message, in_conversation_with)
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}")

    except Exception as e:
        logger.error(f"Error in chat_with_visitor_controller_v1: {e}")

async def team_member_start_conversation_controller(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import update_visitor_conversation_status
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_conversation_started
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        # Get user_id from the team member's session
        session = await sio.get_session(sid)
        user_id = session.get("user_id") if session else None

        visitor_sid = update_visitor_conversation_status(agent_id, chat_session_id, user_id)
        if visitor_sid:
            await emit_conversation_started(visitor_sid, agent_id, chat_session_id, user_id)
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}")

    except Exception as e:
        logger.error(f"Error in team_member_start_conversation_controller: {e}")

async def team_member_end_conversation_controller(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import update_visitor_conversation_status
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_conversation_ended

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        visitor_sid = update_visitor_conversation_status(agent_id, chat_session_id, None)
        if visitor_sid:
            await emit_conversation_ended(visitor_sid, agent_id, chat_session_id)
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}")

    except Exception as e:
        logger.error(f"Error in team_member_end_conversation_controller: {e}")