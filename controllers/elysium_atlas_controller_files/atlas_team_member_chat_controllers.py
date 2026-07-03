from logging_config import get_logger
import uuid
import datetime
import asyncio

from services.socket_connection_helpers import resolve_socket_user_id

logger = get_logger()


async def chat_with_visitor_controller_v1(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import get_visitor_sid_by_chat_session
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_visitor_message
        from services.elysium_atlas_services.atlas_chat_session_services import (
            create_and_store_chat_messages,
            coerce_utc_datetime,
            stored_message_metadata,
        )
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")
        message = socketData.get("message")

        # Get the team member's user_id from their socket session
        session = await sio.get_session(sid)
        team_member_id = resolve_socket_user_id(session)

        if not agent_id or not chat_session_id or message is None:
            logger.warning("atlas team member message missing agent_id/chat_session_id/message")
            return {"success": False, "message": "agent_id, chat_session_id and message are required"}
        
        message_arrived_at = coerce_utc_datetime(socketData.get("_message_received_at"))

        message_payload = {
            "message_id": str(uuid.uuid4()),
            "role": "human",
            "content": message,
            "created_at": message_arrived_at,
        }
        if team_member_id:
            message_payload["team_member_id"] = team_member_id

        stored_messages = await create_and_store_chat_messages(
            chat_session_id=chat_session_id,
            agent_id=agent_id,
            user_message_payload=None,
            agent_message_payload=message_payload,
        )
        message_metadata = stored_message_metadata(stored_messages[0] if stored_messages else None)

        # Track team member participation on the chat session (idempotent, async)
        if team_member_id:
            from services.mongo_services import get_collection
            async def _add_team_member_id():
                collection = get_collection("atlas_chat_sessions")
                await collection.update_one(
                    {"chat_session_id": chat_session_id, "agent_id": agent_id},
                    {"$addToSet": {"team_member_ids": team_member_id}}
                )
                logger.info(f"Added team_member_id {team_member_id} to team_member_ids for chat_session_id {chat_session_id}")
            asyncio.create_task(_add_team_member_id())

        # Attempt to emit to visitor if they're online
        visitor_sid = get_visitor_sid_by_chat_session(agent_id, chat_session_id)
        if visitor_sid:
            await emit_visitor_message(
                visitor_sid,
                agent_id,
                chat_session_id,
                message,
                team_member_id,
                message_metadata=message_metadata,
            )
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}. Message stored to DB.")

        async def _mirror_team_member_to_privileged_monitors() -> None:
            try:
                from services.elysium_atlas_services.atlas_team_member_emit_services import (
                    get_privileged_takeover_mirror_monitor_sids,
                    emit_monitor_team_member_message,
                )

                monitor_sids = await get_privileged_takeover_mirror_monitor_sids(
                    agent_id,
                    chat_session_id,
                    exclude_user_id=team_member_id,
                )
                if monitor_sids:
                    await emit_monitor_team_member_message(
                        monitor_sids,
                        agent_id,
                        chat_session_id,
                        message,
                        message_metadata,
                        team_member_id=team_member_id,
                    )
            except Exception as emit_err:
                logger.error(
                    f"Failed to mirror team member message to monitors for {chat_session_id}: {emit_err}",
                    exc_info=True,
                )

        asyncio.create_task(_mirror_team_member_to_privileged_monitors())

        return {"success": True, "message": "Message stored and emitted if visitor present"}

    except Exception as e:
        logger.error(f"Error in chat_with_visitor_controller_v1: {e}")
        return {"success": False, "message": "An error occurred while handling the team-member message."}

async def team_member_start_conversation_controller(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import (
            remove_session_monitor,
            is_session_monitor,
        )
        from services.elysium_atlas_services.atlas_chat_session_services import (
            resolve_active_conversation_handler,
            persist_in_conversation_with,
        )
        from services.elysium_atlas_services.atlas_team_member_emit_services import (
            emit_conversation_started,
            emit_team_member_conversation_started,
            emit_team_member_conversation_takeover_denied,
            emit_monitor_conversation_ended,
            notify_monitors_on_takeover_started,
        )
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        session = await sio.get_session(sid)
        user_id = resolve_socket_user_id(session)

        if not agent_id or not chat_session_id or not user_id:
            logger.warning("atlas-team-member-start-conversation missing agent_id/chat_session_id/user_id")
            await sio.emit(
                "conversation_started",
                {
                    "success": False,
                    "message": "agent_id, chat_session_id and authenticated user_id are required",
                    "agent_id": agent_id,
                    "chat_session_id": chat_session_id,
                },
                to=sid,
            )
            return

        active_handler = await resolve_active_conversation_handler(agent_id, chat_session_id)

        if active_handler and active_handler != user_id:
            await emit_team_member_conversation_takeover_denied(
                sid, agent_id, chat_session_id, active_handler
            )
            return

        if active_handler == user_id:
            await emit_team_member_conversation_started(
                sid,
                agent_id,
                chat_session_id,
                user_id,
                switched_from_monitor=False,
            )
            return

        switched_from_monitor = is_session_monitor(agent_id, chat_session_id, user_id, sid=sid)
        remove_session_monitor(agent_id, chat_session_id, user_id, sid=sid)

        visitor_sid = await persist_in_conversation_with(
            agent_id, chat_session_id, user_id, actor_user_id=user_id
        )
        if visitor_sid:
            await emit_conversation_started(visitor_sid, agent_id, chat_session_id, user_id)
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}")

        if switched_from_monitor:
            await emit_monitor_conversation_ended(
                sid,
                agent_id,
                chat_session_id,
                reason="switched_to_takeover",
            )
        await emit_team_member_conversation_started(
            sid,
            agent_id,
            chat_session_id,
            user_id,
            switched_from_monitor=switched_from_monitor,
        )

        await notify_monitors_on_takeover_started(agent_id, chat_session_id, user_id)

    except Exception as e:
        logger.error(f"Error in team_member_start_conversation_controller: {e}")


async def team_member_monitor_conversation_controller(sid, socketData):
    """
    Passive monitor: visitor ↔ AI chat continues; team member receives mirrored messages.
    """
    try:
        from services.elysium_atlas_services.atlas_redis_services import (
            add_session_monitor,
        )
        from services.elysium_atlas_services.atlas_chat_session_services import (
            resolve_active_conversation_handler,
        )
        from services.elysium_atlas_services.team_auth_services import (
            user_has_agent_team_role,
            TEAM_ADMIN_ROLES,
        )
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        session = await sio.get_session(sid)
        user_id = resolve_socket_user_id(session)

        if not agent_id or not chat_session_id or not user_id:
            logger.warning("atlas-team-member-monitor-conversation missing agent_id/chat_session_id/user_id")
            await sio.emit(
                "monitor_conversation_started",
                {
                    "success": False,
                    "message": "agent_id, chat_session_id and authenticated user_id are required",
                    "agent_id": agent_id,
                    "chat_session_id": chat_session_id,
                },
                to=sid,
            )
            return

        active_handler = await resolve_active_conversation_handler(agent_id, chat_session_id)

        if active_handler:
            can_mirror_takeover = await user_has_agent_team_role(user_id, agent_id, TEAM_ADMIN_ROLES)
            if not can_mirror_takeover:
                await sio.emit(
                    "monitor_conversation_started",
                    {
                        "success": False,
                        "message": "Only team owners and admins can monitor during an active human takeover",
                        "agent_id": agent_id,
                        "chat_session_id": chat_session_id,
                        "in_conversation_with": active_handler,
                        "takeover_active": True,
                    },
                    to=sid,
                )
                return

        add_session_monitor(agent_id, chat_session_id, user_id, sid)
        ack_payload: dict = {
            "success": True,
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "conversation_mode": "monitor",
        }
        if active_handler:
            ack_payload["in_conversation_with"] = active_handler
            ack_payload["takeover_active"] = True
            ack_payload["takeover_mirror_enabled"] = True

        await sio.emit("monitor_conversation_started", ack_payload, to=sid)
        logger.info(
            f"Team member {user_id} (sid {sid}) monitoring chat_session_id {chat_session_id} "
            f"for agent {agent_id}"
        )

    except Exception as e:
        logger.error(f"Error in team_member_monitor_conversation_controller: {e}")


async def team_member_stop_monitor_conversation_controller(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import remove_session_monitor
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_monitor_conversation_ended
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        session = await sio.get_session(sid)
        user_id = resolve_socket_user_id(session)

        if agent_id and chat_session_id and user_id:
            remove_session_monitor(agent_id, chat_session_id, user_id, sid=sid)

        await emit_monitor_conversation_ended(
            sid,
            agent_id,
            chat_session_id,
            reason="stopped",
        )
        logger.info(
            f"Team member {user_id} (sid {sid}) stopped monitoring chat_session_id {chat_session_id} "
            f"for agent {agent_id}"
        )

    except Exception as e:
        logger.error(f"Error in team_member_stop_monitor_conversation_controller: {e}")

async def team_member_end_conversation_controller(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import get_session_monitor_sids
        from services.elysium_atlas_services.atlas_chat_session_services import persist_in_conversation_with
        from services.elysium_atlas_services.atlas_team_member_emit_services import (
            emit_conversation_ended,
            emit_session_takeover_ended_to_monitors,
        )
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        session = await sio.get_session(sid)
        user_id = resolve_socket_user_id(session)

        monitor_sids = get_session_monitor_sids(agent_id, chat_session_id) if agent_id and chat_session_id else []

        visitor_sid = await persist_in_conversation_with(
            agent_id,
            chat_session_id,
            None,
            actor_user_id=user_id,
        )
        if visitor_sid:
            await emit_conversation_ended(visitor_sid, agent_id, chat_session_id)
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}")

        if monitor_sids:
            await emit_session_takeover_ended_to_monitors(monitor_sids, agent_id, chat_session_id)

    except Exception as e:
        logger.error(f"Error in team_member_end_conversation_controller: {e}")


async def team_member_resolve_session_controller(sid, socketData):
    """Mark a visitor chat session as resolved (team member action)."""
    try:
        from services.elysium_atlas_services.atlas_chat_session_services import mark_chat_session_resolved
        from services.elysium_atlas_services.atlas_team_member_emit_services import (
            emit_chat_session_resolved,
            emit_chat_session_status_updated,
            emit_conversation_ended,
        )
        from services.elysium_atlas_services.team_auth_services import (
            TEAM_ADMIN_ROLES,
            user_has_agent_team_role,
        )
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        session = await sio.get_session(sid)
        user_id = resolve_socket_user_id(session)

        if not agent_id or not chat_session_id or not user_id:
            await emit_chat_session_resolved(
                sid,
                agent_id,
                chat_session_id,
                success=False,
                message="agent_id, chat_session_id and authenticated user_id are required",
            )
            return

        is_privileged_resolver = await user_has_agent_team_role(
            user_id, agent_id, TEAM_ADMIN_ROLES
        )

        result = await mark_chat_session_resolved(
            agent_id,
            chat_session_id,
            resolved_by=user_id,
            allow_privileged_resolve=is_privileged_resolver,
        )

        if not result.get("success"):
            await emit_chat_session_resolved(
                sid,
                agent_id,
                chat_session_id,
                success=False,
                message=result.get("message", "Failed to mark session as resolved"),
                in_conversation_with=result.get("in_conversation_with"),
            )
            return

        visitor_sid = result.get("visitor_sid")
        if visitor_sid:
            await emit_conversation_ended(visitor_sid, agent_id, chat_session_id)

        await emit_chat_session_resolved(
            sid,
            agent_id,
            chat_session_id,
            success=True,
            status=result.get("status"),
            resolved_at=result.get("resolved_at"),
            resolved_by=result.get("resolved_by"),
            audit=result.get("audit"),
            already_resolved=result.get("already_resolved", False),
        )

        if not result.get("already_resolved"):
            await emit_chat_session_status_updated(
                agent_id,
                chat_session_id,
                status=result.get("status"),
                resolved_at=result.get("resolved_at"),
                resolved_by=result.get("resolved_by"),
            )

    except Exception as e:
        logger.error(f"Error in team_member_resolve_session_controller: {e}")