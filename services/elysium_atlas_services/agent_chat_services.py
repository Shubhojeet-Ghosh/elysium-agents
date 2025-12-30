from logging_config import get_logger

logger = get_logger()

def chat_with_agent_v1(agent_id, message,sid = None):
    try:
        
        return {"success":True,"message": "Chat processed successfully."}
        
    
    except Exception as e:
        logger.error(f"Error in chat_with_agent_v1: {e}")
        return {"success":False,"message": "An error occurred while processing the chat."}