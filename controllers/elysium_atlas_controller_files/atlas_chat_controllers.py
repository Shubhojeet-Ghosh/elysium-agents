from logging_config import get_logger

from services.socket_emit_services import emit_atlas_response
from services.elysium_atlas_services.agent_chat_services import chat_with_agent_v1

logger = get_logger()

async def chat_with_agent_controller_v1(chatPayload,user_data, sid = None):
    try:
        
        agent_id = chatPayload.get("agent_id")
        message = chatPayload.get("message")
        
        chat_response = await chat_with_agent_v1(agent_id, message,sid)

        emit_status = await emit_atlas_response(sid=sid, message="Response from agent", payload=chat_response)

        return {"success":True,"message": "Chat processed successfully."}
    
    except Exception as e:
        logger.error(f"Error in chat_with_agent_v1: {e}")
        return {"success":False,"message": "An error occurred while processing the chat."}