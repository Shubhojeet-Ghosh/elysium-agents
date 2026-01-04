from logging_config import get_logger

from services.socket_emit_services import emit_atlas_response
from services.elysium_atlas_services.agent_chat_services import chat_with_agent_v1

logger = get_logger()

async def chat_with_agent_controller_v1(chatPayload,user_data, sid = None):
    try:
        
        logger.info(f"chat_with_agent_controller_v1 called with payload: {chatPayload} and user_data: {user_data}")
        agent_id = chatPayload.get("agent_id")
        message = chatPayload.get("message")
        chat_session_id = chatPayload.get("chat_session_id")
        
        chat_response = await chat_with_agent_v1(agent_id, message, sid, chat_session_id=chat_session_id,additional_params=chatPayload)

        # emit_status = await emit_atlas_response(sid=sid, message="Response from agent", payload=chat_response)

        return {"success":True,"message": "Chat processed successfully.","chat_response": chat_response}
    
    except Exception as e:
        logger.error(f"Error in chat_with_agent_v1: {e}")
        return {"success":False,"message": "An error occurred while processing the chat."}