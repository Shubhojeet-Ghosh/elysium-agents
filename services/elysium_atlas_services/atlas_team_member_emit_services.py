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

async def emit_team_member_message(
    team_member_sids,
    agent_id,
    chat_session_id,
    message,
    chat_session_id_sender,
    message_metadata=None,
    *,
    conversation_mode: str | None = None,
):
    """
    Emit a visitor's message to one or more team member sockets.

    Args:
        team_member_sids (list[str]): Socket IDs of the target team member
        agent_id (str): The agent ID
        chat_session_id (str): The visitor's chat session ID
        message (str): The message content
        chat_session_id_sender (str): Same as chat_session_id, passed for clarity
        message_metadata (dict | None): Persisted message fields (_id, message_id, created_at, role)
        conversation_mode (str | None): e.g. "monitor" or "takeover" for passive mirror consumers
    """
    from sockets import sio
    payload = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "message": message,
        "sender": "visitor",
    }
    if conversation_mode:
        payload["conversation_mode"] = conversation_mode
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


async def emit_team_member_conversation_started(
    team_member_sid: str,
    agent_id: str,
    chat_session_id: str,
    user_id: str,
    *,
    switched_from_monitor: bool = False,
) -> None:
    """Notify the team member socket that human takeover is active for this session."""
    from sockets import sio

    await sio.emit(
        "conversation_started",
        {
            "success": True,
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "in_conversation_with": user_id,
            "conversation_mode": "takeover",
            "switched_from_monitor": switched_from_monitor,
        },
        to=team_member_sid,
    )
    logger.info(
        f"Emitted conversation_started to team member sid {team_member_sid} "
        f"for chat_session_id {chat_session_id}, agent {agent_id}, user_id {user_id}"
    )


async def emit_team_member_conversation_takeover_denied(
    team_member_sid: str,
    agent_id: str,
    chat_session_id: str,
    in_conversation_with: str,
) -> None:
    """Reject takeover — another team member already holds this session."""
    from sockets import sio

    await sio.emit(
        "conversation_started",
        {
            "success": False,
            "message": "This chat is already handled by another team member",
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "in_conversation_with": in_conversation_with,
            "conversation_mode": "takeover",
        },
        to=team_member_sid,
    )
    logger.info(
        f"Denied takeover for sid {team_member_sid} on chat_session_id {chat_session_id}: "
        f"already handled by {in_conversation_with}"
    )


async def emit_monitor_conversation_ended(
    team_member_sid: str,
    agent_id: str,
    chat_session_id: str,
    *,
    reason: str = "stopped",
) -> None:
    """Notify a team member socket that passive monitoring ended."""
    from sockets import sio

    await sio.emit(
        "monitor_conversation_ended",
        {
            "success": True,
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "reason": reason,
        },
        to=team_member_sid,
    )
    logger.info(
        f"Emitted monitor_conversation_ended (reason={reason}) to sid {team_member_sid} "
        f"for chat_session_id {chat_session_id}, agent {agent_id}"
    )


async def emit_session_takeover_started_to_monitors(
    monitor_sids: list[str],
    agent_id: str,
    chat_session_id: str,
    taken_over_by: str,
) -> None:
    """
    Notify remaining passive monitors that another team member started human takeover.
    Their monitor registration stays active; AI mirror pauses until takeover ends.
    """
    if not monitor_sids:
        return

    from sockets import sio

    payload = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "in_conversation_with": taken_over_by,
        "conversation_mode": "takeover",
    }
    for member_sid in monitor_sids:
        await sio.emit("session_takeover_started", payload, to=member_sid)
    logger.info(
        f"Emitted session_takeover_started to {len(monitor_sids)} monitor socket(s) "
        f"for chat_session_id {chat_session_id}, agent {agent_id}, taken_over_by={taken_over_by}"
    )


async def emit_session_takeover_ended_to_monitors(
    monitor_sids: list[str],
    agent_id: str,
    chat_session_id: str,
) -> None:
    """Notify passive monitors that human takeover ended and AI mirror can resume."""
    if not monitor_sids:
        return

    from sockets import sio

    payload = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "in_conversation_with": None,
        "conversation_mode": "monitor",
    }
    for member_sid in monitor_sids:
        await sio.emit("session_takeover_ended", payload, to=member_sid)
    logger.info(
        f"Emitted session_takeover_ended to {len(monitor_sids)} monitor socket(s) "
        f"for chat_session_id {chat_session_id}, agent {agent_id}"
    )

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


async def emit_chat_session_resolved(
    sid: str,
    agent_id: str | None,
    chat_session_id: str | None,
    *,
    success: bool,
    message: str | None = None,
    status: str | None = None,
    resolved_at: str | None = None,
    resolved_by: str | None = None,
    audit: dict | None = None,
    already_resolved: bool = False,
    in_conversation_with: str | None = None,
) -> None:
    """Ack to the team member who marked a session resolved."""
    from sockets import sio

    payload: dict = {
        "success": success,
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
    }
    if message is not None:
        payload["message"] = message
    if not success and in_conversation_with is not None:
        payload["in_conversation_with"] = in_conversation_with
    if success:
        payload["status"] = status
        payload["resolved_at"] = resolved_at
        payload["resolved_by"] = resolved_by
        payload["already_resolved"] = already_resolved
        if audit:
            payload["audit"] = audit

    await sio.emit("chat_session_resolved", payload, to=sid)
    logger.info(
        "Emitted chat_session_resolved success=%s chat_session_id=%s agent_id=%s",
        success,
        chat_session_id,
        agent_id,
    )


async def emit_chat_session_status_updated(
    agent_id: str,
    chat_session_id: str,
    *,
    status: str,
    resolved_at: str | None = None,
    resolved_by: str | None = None,
    reactivated_at: str | None = None,
    previous_status: str | None = None,
) -> None:
    """Broadcast session status changes to all team members on the agent dashboard."""
    from sockets import sio

    payload: dict = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "status": status,
    }
    if resolved_at is not None:
        payload["resolved_at"] = resolved_at
    if resolved_by is not None:
        payload["resolved_by"] = resolved_by
    if reactivated_at is not None:
        payload["reactivated_at"] = reactivated_at
    if previous_status is not None:
        payload["previous_status"] = previous_status

    await sio.emit("chat_session_status_updated", payload, room=f"agent_{agent_id}_members")
    logger.info(
        "Emitted chat_session_status_updated status=%s chat_session_id=%s agent_id=%s",
        status,
        chat_session_id,
        agent_id,
    )


async def get_privileged_takeover_mirror_monitor_sids(
    agent_id: str,
    chat_session_id: str,
    exclude_user_id: str | None = None,
) -> list[str]:
    """
    Socket IDs of owner/admin monitors who may receive live takeover mirrors.

    Regular team members (role=member) are excluded.
    """
    from services.elysium_atlas_services.atlas_redis_services import get_session_monitors
    from services.elysium_atlas_services.team_auth_services import (
        get_agent_team_id,
        get_user_role_for_team,
        TEAM_ADMIN_ROLES,
    )

    team_id = await get_agent_team_id(agent_id)
    if not team_id:
        return []

    monitors = get_session_monitors(agent_id, chat_session_id)
    if not monitors:
        return []

    role_cache: dict[str, str | None] = {}
    privileged_sids: list[str] = []

    for monitor in monitors:
        monitor_user_id = monitor.get("user_id")
        monitor_sid = monitor.get("sid")
        if not monitor_user_id or not monitor_sid:
            continue
        if exclude_user_id and monitor_user_id == exclude_user_id:
            continue
        if monitor_user_id not in role_cache:
            role_cache[monitor_user_id] = await get_user_role_for_team(monitor_user_id, team_id)
        if role_cache[monitor_user_id] in TEAM_ADMIN_ROLES:
            privileged_sids.append(
                monitor_sid if isinstance(monitor_sid, str) else monitor_sid.decode()
            )

    return privileged_sids


async def notify_monitors_on_takeover_started(
    agent_id: str,
    chat_session_id: str,
    taken_over_by: str,
) -> None:
    """
    Owner/admin monitors stay subscribed and receive session_takeover_started.
    Member-role monitors are removed — they cannot watch human takeover chat.
    """
    from services.elysium_atlas_services.atlas_redis_services import (
        get_session_monitors,
        remove_session_monitor,
    )
    from services.elysium_atlas_services.team_auth_services import (
        get_agent_team_id,
        get_user_role_for_team,
        TEAM_ADMIN_ROLES,
        MEMBER_ROLE,
    )

    team_id = await get_agent_team_id(agent_id)
    if not team_id:
        return

    monitors = get_session_monitors(agent_id, chat_session_id)
    privileged_sids: list[str] = []
    role_cache: dict[str, str | None] = {}

    for monitor in monitors:
        monitor_user_id = monitor.get("user_id")
        monitor_sid = monitor.get("sid")
        if not monitor_user_id or not monitor_sid or monitor_user_id == taken_over_by:
            continue

        if monitor_user_id not in role_cache:
            role_cache[monitor_user_id] = await get_user_role_for_team(monitor_user_id, team_id)

        sid_str = monitor_sid if isinstance(monitor_sid, str) else monitor_sid.decode()
        role = role_cache[monitor_user_id]

        if role in TEAM_ADMIN_ROLES:
            privileged_sids.append(sid_str)
        elif role == MEMBER_ROLE:
            remove_session_monitor(agent_id, chat_session_id, monitor_user_id, sid=sid_str)
            await emit_monitor_conversation_ended(
                sid_str,
                agent_id,
                chat_session_id,
                reason="takeover_restricted",
            )

    if privileged_sids:
        await emit_session_takeover_started_to_monitors(
            privileged_sids,
            agent_id,
            chat_session_id,
            taken_over_by,
        )


async def emit_monitor_team_member_message(
    team_member_sids: list[str],
    agent_id: str,
    chat_session_id: str,
    message: str,
    message_metadata: dict | None,
    team_member_id: str | None = None,
) -> None:
    """Emit a human handler reply to owner/admin passive monitors during takeover."""
    if not team_member_sids or not message_metadata:
        return

    from sockets import sio

    payload: dict = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "message": message,
        "sender": "team_member",
        "conversation_mode": "takeover",
        "role": "human",
    }
    if team_member_id:
        payload["team_member_id"] = team_member_id
    payload.update(message_metadata)

    for member_sid in team_member_sids:
        await sio.emit("message_from_team_member", payload, to=member_sid)
    logger.info(
        f"Emitted message_from_team_member to {len(team_member_sids)} monitor socket(s) "
        f"for chat_session_id {chat_session_id}, agent {agent_id}"
    )


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


async def emit_monitor_agent_message(
    team_member_sids: list[str],
    agent_id: str,
    chat_session_id: str,
    agent_message: dict | None,
) -> None:
    """
    Emit a completed AI agent reply to team members passively monitoring a session.

    Fired only after the full response has been streamed to the visitor.
    """
    if not team_member_sids or not agent_message:
        return

    from sockets import sio

    payload: dict = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "sender": "agent",
        "conversation_mode": "monitor",
    }
    if agent_message.get("message_id"):
        payload["message_id"] = agent_message["message_id"]
    if agent_message.get("_id"):
        payload["_id"] = agent_message["_id"]
    if agent_message.get("content") is not None:
        payload["message"] = agent_message["content"]
        payload["content"] = agent_message["content"]
    if agent_message.get("created_at"):
        payload["created_at"] = agent_message["created_at"]
    if agent_message.get("role"):
        payload["role"] = agent_message["role"]

    for member_sid in team_member_sids:
        await sio.emit("message_from_agent", payload, to=member_sid)
    logger.info(
        f"Emitted message_from_agent to {len(team_member_sids)} monitor socket(s) "
        f"for chat_session_id {chat_session_id}, agent {agent_id}"
    )


async def emit_monitor_visitor_message(
    team_member_sids: list[str],
    agent_id: str,
    chat_session_id: str,
    message: str,
    message_metadata: dict | None,
    *,
    conversation_mode: str = "monitor",
) -> None:
    """Emit a persisted visitor message to passive session monitors (non-blocking from caller)."""
    if not team_member_sids or not message_metadata:
        return

    await emit_team_member_message(
        team_member_sids,
        agent_id,
        chat_session_id,
        message,
        chat_session_id,
        message_metadata=message_metadata,
        conversation_mode=conversation_mode,
    )
