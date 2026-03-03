import asyncio
import uuid
import datetime
from logging_config import get_logger

from services.socket_emit_services import emit_atlas_response, emit_atlas_response_chunk
from services.elysium_atlas_services.agent_chat_services import chat_with_agent_v1
from services.elysium_atlas_services.elysium_atlas_user_plan_services import can_user_send_chat, decrement_user_ai_queries
from services.elysium_atlas_services.agent_db_operations import get_agent_owner_user_id
from services.elysium_atlas_services.atlas_chat_session_services import rotate_conversation_id, create_and_store_chat_messages

logger = get_logger()

async def route_visitor_message_to_team_member(agent_id, chat_session_id, message, in_conversation_with, sid=None):
    """
    Route a visitor's message directly to a specific team member.
    Emits via socket and always persists the message to the DB.

    Args:
        agent_id (str): The agent ID
        chat_session_id (str): The visitor's chat session ID
        message (str): The message content
        in_conversation_with (str): user_id of the target team member
        sid (str | None): Visitor's socket ID (unused here, kept for symmetry)
    """
    try:
        from services.elysium_atlas_services.atlas_redis_services import get_agent_member_sids_by_user_id
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_team_member_message

        message_id = str(uuid.uuid4())
        created_at = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        # Build visitor message payload
        visitor_message_payload = {
            "message_id": message_id,
            "role": "user",
            "content": message,
            "created_at": created_at
        }

        # Always persist regardless of whether the team member is online
        asyncio.create_task(create_and_store_chat_messages(
            chat_session_id=chat_session_id,
            agent_id=agent_id,
            user_message_payload=visitor_message_payload,
            agent_message_payload=None,
        ))

        # Emit to team member sockets if any are online
        team_member_sids = get_agent_member_sids_by_user_id(agent_id, in_conversation_with)
        if team_member_sids:
            await emit_team_member_message(team_member_sids, agent_id, chat_session_id, message, chat_session_id)
        else:
            logger.warning(
                f"Team member {in_conversation_with} is not online for agent {agent_id}. "
                f"Message stored to DB only."
            )

        return {"success": True, "message": "Message routed to team member"}

    except Exception as e:
        logger.error(f"Error in route_visitor_message_to_team_member: {e}")
        return {"success": False, "message": "An error occurred while routing message to team member"}


async def chat_with_agent_controller_v1(chatPayload,user_data, sid = None):
    try:
        
        logger.info(f"chat_with_agent_controller_v1 called with payload: {chatPayload} and user_data: {user_data}")

        agent_id = chatPayload.get("agent_id")
        message = chatPayload.get("message")
        chat_session_id = chatPayload.get("chat_session_id")
        in_conversation_with = chatPayload.get("in_conversation_with")

        # If the visitor is in a conversation with a team member, route directly to them
        if in_conversation_with:
            return await route_visitor_message_to_team_member(
                agent_id, chat_session_id, message, in_conversation_with, sid
            )

        user_id = await get_agent_owner_user_id(agent_id) if agent_id else None
        if user_id:
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
                        role="agent"
                    )
                return {"success": False, "message": internal_message}

        chat_response = await chat_with_agent_v1(agent_id, message, sid, chat_session_id=chat_session_id,additional_params=chatPayload)

        if user_id and chat_response.get("success"):
            asyncio.create_task(decrement_user_ai_queries(user_id))

        # emit_status = await emit_atlas_response(sid=sid, message="Response from agent", payload=chat_response)

        return {"success":True,"message": "Chat processed successfully.","chat_response": chat_response}
    
    except Exception as e:
        logger.error(f"Error in chat_with_agent_v1: {e}")
        return {"success":False,"message": "An error occurred while processing the chat."}


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