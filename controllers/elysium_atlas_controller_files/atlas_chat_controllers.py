import asyncio
from logging_config import get_logger

from services.socket_emit_services import emit_atlas_response, emit_atlas_response_chunk
from services.elysium_atlas_services.agent_chat_services import chat_with_agent_v1
from services.elysium_atlas_services.elysium_atlas_user_plan_services import can_user_send_chat, decrement_user_ai_queries

logger = get_logger()

async def chat_with_agent_controller_v1(chatPayload,user_data, sid = None):
    try:
        
        logger.info(f"chat_with_agent_controller_v1 called with payload: {chatPayload} and user_data: {user_data}")

        user_id = user_data.get("user_id") if user_data else None
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

        agent_id = chatPayload.get("agent_id")
        message = chatPayload.get("message")
        chat_session_id = chatPayload.get("chat_session_id")
        
        chat_response = await chat_with_agent_v1(agent_id, message, sid, chat_session_id=chat_session_id,additional_params=chatPayload)

        if user_id and chat_response.get("success"):
            asyncio.create_task(decrement_user_ai_queries(user_id))

        # emit_status = await emit_atlas_response(sid=sid, message="Response from agent", payload=chat_response)

        return {"success":True,"message": "Chat processed successfully.","chat_response": chat_response}
    
    except Exception as e:
        logger.error(f"Error in chat_with_agent_v1: {e}")
        return {"success":False,"message": "An error occurred while processing the chat."}