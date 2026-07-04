"""Per-user Socket.IO rooms for Atlas team member message routing (ephemeral)."""

from __future__ import annotations

from logging_config import get_logger

logger = get_logger()

USER_ROOM_PREFIX = "atlas_user_"


def team_member_user_room(user_id: str) -> str:
    return f"{USER_ROOM_PREFIX}{user_id}"


async def enter_team_member_user_room(sid: str, user_id: str) -> None:
    if not sid or not user_id:
        return
    from sockets import sio

    room = team_member_user_room(user_id)
    await sio.enter_room(sid, room)
    logger.debug(f"Socket {sid} joined team member user room {room}")


