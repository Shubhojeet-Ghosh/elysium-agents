"""Per-session Socket.IO rooms for Atlas visitor message routing (ephemeral)."""

from __future__ import annotations

from logging_config import get_logger

logger = get_logger()

VISITOR_SESSION_ROOM_PREFIX = "atlas_chat_session_"


def visitor_session_room(chat_session_id: str) -> str:
    return f"{VISITOR_SESSION_ROOM_PREFIX}{chat_session_id}"


async def enter_visitor_session_room(sid: str, chat_session_id: str) -> None:
    if not sid or not chat_session_id:
        return
    from sockets import sio

    room = visitor_session_room(chat_session_id)
    await sio.enter_room(sid, room)
    logger.debug(f"Socket {sid} joined visitor session room {room}")


async def visitor_session_room_has_connections(
    chat_session_id: str,
    *,
    exclude_sid: str | None = None,
) -> bool:
    """True when another socket (excluding exclude_sid) is still in the session room."""
    if not chat_session_id:
        return False

    from sockets import sio

    room = visitor_session_room(chat_session_id)
    namespace = "/"
    try:
        participants = sio.manager.get_participants(namespace, room)
        if hasattr(participants, "__aiter__"):
            async for participant in participants:
                pid = participant[0] if isinstance(participant, tuple) else participant
                if exclude_sid and pid == exclude_sid:
                    continue
                return True
            return False

        for participant in participants:
            pid = participant[0] if isinstance(participant, tuple) else participant
            if exclude_sid and pid == exclude_sid:
                continue
            return True
        return False
    except Exception as e:
        logger.warning(f"Could not list participants for room {room}: {e}")
        return False
