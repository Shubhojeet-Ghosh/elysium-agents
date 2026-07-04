import asyncio
import uuid
from fastapi.responses import JSONResponse
from logging_config import get_logger

from services.socket_emit_services import emit_atlas_response, emit_atlas_response_chunk
from services.elysium_atlas_services.agent_chat_services import chat_with_agent_v1
from services.elysium_atlas_services.elysium_atlas_user_plan_services import can_user_send_chat, decrement_user_ai_queries
from services.elysium_atlas_services.agent_db_operations import get_agent_owner_user_id
from services.elysium_atlas_services.atlas_team_member_emit_services import emit_agent_visitor_ai_chat_message
from services.elysium_atlas_services.atlas_chat_session_services import (
    rotate_conversation_id,
    create_and_store_chat_messages,
    coerce_utc_datetime,
    mark_chat_message_as_read,
    stored_message_metadata,
)

logger = get_logger()


async def route_visitor_message_to_team_member(
    agent_id,
    chat_session_id,
    message,
    in_conversation_with,
    sid=None,
    message_received_at=None,
):
    """Route a visitor message to the human handler; mirror to session monitors async."""
    try:
        from services.elysium_atlas_services.atlas_presence_services import (
            is_team_member_online_for_agent,
        )
        from services.elysium_atlas_services.atlas_team_member_emit_services import (
            emit_team_member_message_to_user,
            mirror_takeover_visitor_message_to_monitors,
        )

        visitor_message_payload = {
            "message_id": str(uuid.uuid4()),
            "role": "user",
            "content": message,
            "created_at": coerce_utc_datetime(message_received_at),
        }

        stored_messages = await create_and_store_chat_messages(
            chat_session_id=chat_session_id,
            agent_id=agent_id,
            user_message_payload=visitor_message_payload,
            agent_message_payload=None,
        )
        message_metadata = stored_message_metadata(stored_messages[0] if stored_messages else None)

        if await is_team_member_online_for_agent(agent_id, in_conversation_with):
            await emit_team_member_message_to_user(
                in_conversation_with,
                agent_id,
                chat_session_id,
                message,
                chat_session_id,
                message_metadata=message_metadata,
            )

        asyncio.create_task(
            mirror_takeover_visitor_message_to_monitors(
                agent_id,
                chat_session_id,
                message,
                message_metadata,
                handler_user_id=in_conversation_with,
            )
        )

        return {"success": True, "message": "Message routed to team member"}

    except Exception as e:
        logger.error(f"Error in route_visitor_message_to_team_member: {e}")
        return {"success": False, "message": "An error occurred while routing message to team member"}


async def _resolve_takeover_handler(agent_id: str, chat_session_id: str, payload_handler: str | None) -> str | None:
    """Mongo lookup for active human handler on the live session doc."""
    if payload_handler:
        return str(payload_handler)

    from services.elysium_atlas_services.atlas_presence_services import get_visitor_by_chat_session

    visitor = await get_visitor_by_chat_session(agent_id, chat_session_id)
    if visitor and visitor.get("in_conversation_with"):
        return str(visitor["in_conversation_with"])
    return None


async def chat_with_agent_controller_v1(chatPayload, user_data, sid=None):
    try:
        agent_id = chatPayload.get("agent_id")
        message = chatPayload.get("message")
        chat_session_id = chatPayload.get("chat_session_id")
        in_conversation_with = chatPayload.get("in_conversation_with")

        if agent_id and chat_session_id:
            from services.elysium_atlas_services.atlas_chat_session_services import (
                reactivate_chat_session_if_resolved,
            )
            from services.elysium_atlas_services.atlas_team_member_emit_services import (
                emit_chat_session_status_updated,
            )

            reactivation_payload = await reactivate_chat_session_if_resolved(agent_id, chat_session_id)
            if reactivation_payload:
                await emit_chat_session_status_updated(
                    agent_id,
                    chat_session_id,
                    status=reactivation_payload.get("status"),
                    reactivated_at=reactivation_payload.get("reactivated_at"),
                    previous_status=reactivation_payload.get("previous_status"),
                )

        if not in_conversation_with and agent_id and chat_session_id:
            in_conversation_with = await _resolve_takeover_handler(agent_id, chat_session_id, None)
            if not in_conversation_with:
                from services.elysium_atlas_services.atlas_chat_session_services import (
                    resolve_active_conversation_handler,
                )

                in_conversation_with = await resolve_active_conversation_handler(
                    agent_id, chat_session_id
                )

        if in_conversation_with:
            return await route_visitor_message_to_team_member(
                agent_id,
                chat_session_id,
                message,
                in_conversation_with,
                sid,
                message_received_at=chatPayload.get("_message_received_at"),
            )

        user_id = await get_agent_owner_user_id(agent_id) if agent_id else None

        chat_permission = await can_user_send_chat(user_id, chatPayload)
        if not chat_permission.get("success"):
            internal_message = chat_permission.get("message")
            client_message = chat_permission.get("client_message", internal_message)
            if sid:
                await emit_atlas_response_chunk(
                    "",
                    done=True,
                    sid=sid,
                    full_response=client_message,
                    role="agent",
                )
            return {"success": False, "message": internal_message}

        monitor_sids: list[str] = []
        if agent_id and chat_session_id:
            from services.elysium_atlas_services.atlas_redis_services import get_session_monitor_sids

            monitor_sids = get_session_monitor_sids(agent_id, chat_session_id)
            if monitor_sids:
                chatPayload["_monitor_sids"] = monitor_sids
                chatPayload["_user_message_id"] = str(uuid.uuid4())

        chat_response = await chat_with_agent_v1(
            agent_id, message, sid, chat_session_id=chat_session_id, additional_params=chatPayload
        )

        if not chat_response.get("success"):
            return {
                "success": False,
                "message": chat_response.get("message", "Chat request failed."),
            }

        if agent_id and chat_session_id:
            agent_message = chat_response.get("agent_message")
            if monitor_sids and agent_message:
                from services.elysium_atlas_services.atlas_team_member_emit_services import (
                    emit_monitor_agent_message,
                )

                asyncio.create_task(
                    emit_monitor_agent_message(
                        monitor_sids, agent_id, chat_session_id, agent_message
                    )
                )

            await emit_agent_visitor_ai_chat_message(
                agent_id, chat_session_id, agent_message=agent_message
            )

        if user_id:
            asyncio.create_task(decrement_user_ai_queries(user_id))

        return {"success": True, "message": "Chat processed successfully.", "chat_response": chat_response}

    except Exception as e:
        logger.error(f"Error in chat_with_agent_v1: {e}")
        return {"success": False, "message": "An error occurred while processing the chat."}


async def rotate_conversation_id_controller(requestData: dict):
    try:
        agent_id = requestData.get("agent_id")
        chat_session_id = requestData.get("chat_session_id")

        if not agent_id or not chat_session_id:
            return {"success": False, "message": "agent_id and chat_session_id are required"}

        result = await rotate_conversation_id(agent_id, chat_session_id)
        if not result:
            return {"success": False, "message": "Chat session not found or could not be updated"}

        return {"success": True, "message": "Conversation ID rotated successfully", "data": result}

    except Exception as e:
        logger.error(f"Error in rotate_conversation_id_controller: {e}")
        return {"success": False, "message": "An error occurred while rotating conversation ID"}


async def mark_chat_message_read_controller(requestData: dict):
    """
    Mark a chat message as read.

    Request body:
        message_id       – MongoDB _id or client UUID (message_id field on the doc)
        agent_id         – agent the message belongs to
        chat_session_id  – session the message belongs to
        read_by          – optional; user _id of the reader (team member). Stored only on first read.
    """
    try:
        message_id = requestData.get("message_id")
        agent_id = requestData.get("agent_id")
        chat_session_id = requestData.get("chat_session_id")
        read_by = requestData.get("read_by")

        if not message_id or not agent_id or not chat_session_id:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "message_id, agent_id and chat_session_id are required",
                },
            )

        result = await mark_chat_message_as_read(
            message_id,
            agent_id,
            chat_session_id,
            read_by=read_by,
        )
        if not result.get("success"):
            status_code = 404 if result.get("message") == "Message not found" else 400
            return JSONResponse(
                status_code=status_code,
                content={"success": False, "message": result.get("message", "Failed to mark message as read")},
            )

        return JSONResponse(status_code=200, content=result)

    except Exception as e:
        logger.error(f"Error in mark_chat_message_read_controller: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while marking the message as read"},
        )