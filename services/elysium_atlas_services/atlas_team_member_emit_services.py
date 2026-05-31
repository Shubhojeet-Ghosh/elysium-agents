from logging_config import get_logger

logger = get_logger()

async def emit_visitor_message(visitor_sid, agent_id, chat_session_id, message, in_conversation_with, message_metadata=None):
    """
    Emit a chat message from a team member to a specific visitor's socket.

    Args:
        visitor_sid (str): The visitor's socket ID
        agent_id (str): The agent ID
        chat_session_id (str): The chat session ID
        message (str): The message content
        in_conversation_with (str): The user ID of the team member sending the message
        message_metadata (dict | None): Persisted message fields (_id, message_id, created_at, role)
    """
    from sockets import sio
    payload = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "message": message,
        "sender": "team_member",
        "in_conversation_with": in_conversation_with,
    }
    if message_metadata:
        payload.update(message_metadata)
    await sio.emit("visitor_message", payload, to=visitor_sid)
    logger.info(f"Emitted visitor_message to visitor {chat_session_id} (sid: {visitor_sid}) for agent {agent_id}")

async def emit_team_member_message(team_member_sids, agent_id, chat_session_id, message, chat_session_id_sender, message_metadata=None):
    """
    Emit a visitor's message to one or more team member sockets.

    Args:
        team_member_sids (list[str]): Socket IDs of the target team member
        agent_id (str): The agent ID
        chat_session_id (str): The visitor's chat session ID
        message (str): The message content
        chat_session_id_sender (str): Same as chat_session_id, passed for clarity
        message_metadata (dict | None): Persisted message fields (_id, message_id, created_at, role)
    """
    from sockets import sio
    payload = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "message": message,
        "sender": "visitor",
    }
    if message_metadata:
        payload.update(message_metadata)
    for sid in team_member_sids:
        await sio.emit("message_from_visitor", payload, to=sid)
    logger.info(
        f"Emitted message_from_visitor to {len(team_member_sids)} socket(s) "
        f"for chat_session_id {chat_session_id} agent {agent_id}"
    )


async def emit_conversation_started(visitor_sid, agent_id, chat_session_id, user_id):
    """
    Notify a visitor that a team member has started a conversation with them.

    Args:
        visitor_sid (str): The visitor's socket ID
        agent_id (str): The agent ID
        chat_session_id (str): The chat session ID
        user_id (str): The team member's user ID
    """
    from sockets import sio
    await sio.emit(
        "conversation_started",
        {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "in_conversation_with": user_id
        },
        to=visitor_sid
    )
    logger.info(f"Emitted conversation_started to visitor {chat_session_id} (sid: {visitor_sid}) for agent {agent_id}, user_id {user_id}")

async def emit_conversation_ended(visitor_sid, agent_id, chat_session_id):
    """
    Notify a visitor that the team member has left the conversation.

    Args:
        visitor_sid (str): The visitor's socket ID
        agent_id (str): The agent ID
        chat_session_id (str): The chat session ID
    """
    from sockets import sio
    await sio.emit(
        "conversation_ended",
        {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "in_conversation_with": None
        },
        to=visitor_sid
    )
    logger.info(f"Emitted conversation_ended to visitor {chat_session_id} (sid: {visitor_sid}) for agent {agent_id}")


async def emit_agent_visitor_ai_chat_message(
    agent_id: str,
    chat_session_id: str,
    agent_message: dict | None = None,
):
    """
    Notify connected team members that a visitor with prior agent conversation
    sent a new message to the AI (not in active human takeover).

    Emits to agent_{agent_id}_members room as agent_visitor_ai_chat_message.
    """
    from sockets import sio
    from services.elysium_atlas_services.atlas_redis_services import (
        get_visitor_by_chat_session,
        has_connected_team_members_for_agent,
    )
    from services.elysium_atlas_services.atlas_chat_session_services import (
        session_has_prior_team_member_conversation,
        build_messaging_session_update_payload,
    )

    if not agent_id or not chat_session_id:
        return

    if not await session_has_prior_team_member_conversation(agent_id, chat_session_id):
        logger.debug(
            f"Skipping agent_visitor_ai_chat_message for {chat_session_id}: "
            "no prior team member conversation"
        )
        return

    if not has_connected_team_members_for_agent(agent_id):
        logger.debug(
            f"Skipping agent_visitor_ai_chat_message for {chat_session_id}: "
            "no connected team members"
        )
        return

    visitor = get_visitor_by_chat_session(agent_id, chat_session_id)
    if visitor and visitor.get("in_conversation_with"):
        logger.debug(
            f"Skipping agent_visitor_ai_chat_message for {chat_session_id}: "
            "visitor in human conversation"
        )
        return

    payload = await build_messaging_session_update_payload(
        agent_id,
        chat_session_id,
        last_message=agent_message,
    )
    if not payload:
        return

    agent_members_room = f"agent_{agent_id}_members"
    await sio.emit("agent_visitor_ai_chat_message", payload, room=agent_members_room)
    logger.info(
        f"Emitted agent_visitor_ai_chat_message to room {agent_members_room} "
        f"for chat_session_id {chat_session_id}, agent {agent_id}"
    )
