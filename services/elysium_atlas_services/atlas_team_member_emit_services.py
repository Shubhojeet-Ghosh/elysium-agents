from logging_config import get_logger

logger = get_logger()

async def emit_visitor_message(visitor_sid, agent_id, chat_session_id, message, in_conversation_with):
    """
    Emit a chat message from a team member to a specific visitor's socket.

    Args:
        visitor_sid (str): The visitor's socket ID
        agent_id (str): The agent ID
        chat_session_id (str): The chat session ID
        message (str): The message content
        in_conversation_with (str): The user ID of the team member sending the message
    """
    from sockets import sio
    await sio.emit(
        "visitor_message",
        {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "message": message,
            "sender": "team_member",
            "in_conversation_with": in_conversation_with
        },
        to=visitor_sid
    )
    logger.info(f"Emitted visitor_message to visitor {chat_session_id} (sid: {visitor_sid}) for agent {agent_id}")

async def emit_team_member_message(team_member_sids, agent_id, chat_session_id, message, chat_session_id_sender):
    """
    Emit a visitor's message to one or more team member sockets.

    Args:
        team_member_sids (list[str]): Socket IDs of the target team member
        agent_id (str): The agent ID
        chat_session_id (str): The visitor's chat session ID
        message (str): The message content
        chat_session_id_sender (str): Same as chat_session_id, passed for clarity
    """
    from sockets import sio
    payload = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "message": message,
        "sender": "visitor",
    }
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
