from logging_config import get_logger
import uuid
import asyncio



from services.socket_connection_helpers import (

    resolve_socket_user_id,

    resolve_socket_team_id,

    is_socket_team_admin,

)



logger = get_logger()





def _user_id(session: dict | None) -> str | None:

    return resolve_socket_user_id(session)





async def chat_with_visitor_controller_v1(sid, socketData, session: dict | None = None):

    try:

        from services.elysium_atlas_services.atlas_presence_services import is_visitor_online

        from services.elysium_atlas_services.atlas_team_member_emit_services import (

            emit_visitor_message,

            mirror_takeover_team_member_reply_to_monitors,

        )

        from services.elysium_atlas_services.atlas_chat_session_services import (

            create_and_store_chat_messages,

            coerce_utc_datetime,

            stored_message_metadata,

        )

        from sockets import sio



        agent_id = socketData.get("agent_id")

        chat_session_id = socketData.get("chat_session_id")

        message = socketData.get("message")



        if session is None:

            session = await sio.get_session(sid)

        team_member_id = _user_id(session)



        if not agent_id or not chat_session_id or message is None:

            logger.warning("atlas team member message missing agent_id/chat_session_id/message")

            return {"success": False, "message": "agent_id, chat_session_id and message are required"}



        message_payload = {

            "message_id": str(uuid.uuid4()),

            "role": "human",

            "content": message,

            "created_at": coerce_utc_datetime(socketData.get("_message_received_at")),

        }

        if team_member_id:

            message_payload["team_member_id"] = team_member_id



        stored_messages = await create_and_store_chat_messages(

            chat_session_id=chat_session_id,

            agent_id=agent_id,

            user_message_payload=None,

            agent_message_payload=message_payload,

        )

        human_stored = next(

            (doc for doc in stored_messages if doc.get("role") == "human"),

            stored_messages[-1] if stored_messages else None,

        )

        message_metadata = stored_message_metadata(human_stored)



        if team_member_id:

            from services.mongo_services import get_collection



            async def _add_team_member_id() -> None:

                await get_collection("atlas_chat_sessions").update_one(

                    {"chat_session_id": chat_session_id, "agent_id": agent_id},

                    {"$addToSet": {"team_member_ids": team_member_id}},

                )



            asyncio.create_task(_add_team_member_id())



        if await is_visitor_online(agent_id, chat_session_id):

            await emit_visitor_message(

                agent_id,

                chat_session_id,

                message,

                team_member_id,

                message_metadata=message_metadata,

            )

        else:

            logger.warning(

                f"Visitor offline for agent {agent_id}, chat_session_id {chat_session_id}; message stored"

            )



        if team_member_id:

            asyncio.create_task(

                mirror_takeover_team_member_reply_to_monitors(

                    agent_id,

                    chat_session_id,

                    message,

                    message_metadata,

                    handler_user_id=team_member_id,

                )

            )



        return {"success": True, "message": "Message stored and emitted if visitor present"}



    except Exception as e:

        logger.error(f"Error in chat_with_visitor_controller_v1: {e}")

        return {"success": False, "message": "An error occurred while handling the team-member message."}





async def team_member_start_conversation_controller(sid, socketData, session: dict | None = None):

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

            emit_chat_session_takeover_updated,

        )

        from sockets import sio



        agent_id = socketData.get("agent_id")

        chat_session_id = socketData.get("chat_session_id")



        if session is None:

            session = await sio.get_session(sid)

        user_id = _user_id(session)



        if not agent_id or not chat_session_id or not user_id:

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

                sid, agent_id, chat_session_id, user_id, switched_from_monitor=False

            )

            return



        switched_from_monitor = is_session_monitor(agent_id, chat_session_id, user_id, sid=sid)

        remove_session_monitor(agent_id, chat_session_id, user_id, sid=sid)

        team_id = resolve_socket_team_id(session)
        if team_id:
            from services.elysium_atlas_services.atlas_presence_services import (
                register_team_member_presence,
            )

            await register_team_member_presence(team_id, user_id, agent_id=agent_id)

        visitor_online = await persist_in_conversation_with(

            agent_id, chat_session_id, user_id, actor_user_id=user_id

        )

        if visitor_online:

            await emit_conversation_started(agent_id, chat_session_id, user_id)



        if switched_from_monitor:

            await emit_monitor_conversation_ended(

                sid, agent_id, chat_session_id, reason="switched_to_takeover"

            )

        await emit_team_member_conversation_started(

            sid, agent_id, chat_session_id, user_id, switched_from_monitor=switched_from_monitor

        )

        await notify_monitors_on_takeover_started(agent_id, chat_session_id, user_id)
        await emit_chat_session_takeover_updated(agent_id, chat_session_id)



    except Exception as e:

        logger.error(f"Error in team_member_start_conversation_controller: {e}")





async def team_member_monitor_conversation_controller(sid, socketData, session: dict | None = None):

    try:

        from services.elysium_atlas_services.atlas_redis_services import add_session_monitor

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



        if session is None:

            session = await sio.get_session(sid)

        user_id = _user_id(session)



        if not agent_id or not chat_session_id or not user_id:

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



        if active_handler and not is_socket_team_admin(session):

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

            ack_payload.update(

                in_conversation_with=active_handler,

                takeover_active=True,

                takeover_mirror_enabled=True,

            )



        await sio.emit("monitor_conversation_started", ack_payload, to=sid)



    except Exception as e:

        logger.error(f"Error in team_member_monitor_conversation_controller: {e}")





async def team_member_stop_monitor_conversation_controller(sid, socketData, session: dict | None = None):

    try:

        from services.elysium_atlas_services.atlas_redis_services import remove_session_monitor

        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_monitor_conversation_ended

        from sockets import sio



        agent_id = socketData.get("agent_id")

        chat_session_id = socketData.get("chat_session_id")



        if session is None:

            session = await sio.get_session(sid)

        user_id = _user_id(session)



        if agent_id and chat_session_id and user_id:

            remove_session_monitor(agent_id, chat_session_id, user_id, sid=sid)



        await emit_monitor_conversation_ended(sid, agent_id, chat_session_id, reason="stopped")



    except Exception as e:

        logger.error(f"Error in team_member_stop_monitor_conversation_controller: {e}")





async def team_member_end_conversation_controller(sid, socketData, session: dict | None = None):

    try:

        from services.elysium_atlas_services.atlas_redis_services import get_session_monitor_sids

        from services.elysium_atlas_services.atlas_chat_session_services import persist_in_conversation_with

        from services.elysium_atlas_services.atlas_team_member_emit_services import (

            emit_conversation_ended,
            emit_session_takeover_ended_to_monitors,
            emit_chat_session_takeover_updated,
        )

        from sockets import sio



        agent_id = socketData.get("agent_id")

        chat_session_id = socketData.get("chat_session_id")



        if session is None:

            session = await sio.get_session(sid)

        user_id = _user_id(session)



        monitor_sids = (

            get_session_monitor_sids(agent_id, chat_session_id)

            if agent_id and chat_session_id

            else []

        )



        visitor_online = await persist_in_conversation_with(

            agent_id, chat_session_id, None, actor_user_id=user_id

        )

        if visitor_online:

            await emit_conversation_ended(agent_id, chat_session_id)



        if monitor_sids:
            await emit_session_takeover_ended_to_monitors(monitor_sids, agent_id, chat_session_id)

        await emit_chat_session_takeover_updated(agent_id, chat_session_id)



    except Exception as e:

        logger.error(f"Error in team_member_end_conversation_controller: {e}")





async def team_member_resolve_session_controller(sid, socketData, session: dict | None = None):

    try:

        from services.elysium_atlas_services.atlas_chat_session_services import mark_chat_session_resolved

        from services.elysium_atlas_services.atlas_team_member_emit_services import (

            emit_chat_session_resolved,

            emit_chat_session_status_updated,

            emit_conversation_ended,

            emit_chat_session_takeover_updated,

        )

        from services.elysium_atlas_services.team_auth_services import (

            TEAM_ADMIN_ROLES,

            user_has_agent_team_role,

        )

        from sockets import sio



        agent_id = socketData.get("agent_id")

        chat_session_id = socketData.get("chat_session_id")



        if session is None:

            session = await sio.get_session(sid)

        user_id = _user_id(session)



        if not agent_id or not chat_session_id or not user_id:

            await emit_chat_session_resolved(

                sid,

                agent_id,

                chat_session_id,

                success=False,

                message="agent_id, chat_session_id and authenticated user_id are required",

            )

            return



        is_privileged = is_socket_team_admin(session) or await user_has_agent_team_role(

            user_id, agent_id, TEAM_ADMIN_ROLES

        )



        result = await mark_chat_session_resolved(

            agent_id,

            chat_session_id,

            resolved_by=user_id,

            allow_privileged_resolve=is_privileged,

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



        if result.get("visitor_online"):

            await emit_conversation_ended(agent_id, chat_session_id)



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
            await emit_chat_session_takeover_updated(agent_id, chat_session_id)



    except Exception as e:

        logger.error(f"Error in team_member_resolve_session_controller: {e}")


