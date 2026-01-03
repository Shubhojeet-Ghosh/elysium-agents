from typing import Dict, Any
from logging_config import get_logger
from services.mongo_services import get_collection
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from datetime import datetime, timezone
from bson import ObjectId
import random

logger = get_logger()

async def get_chat_session_data(requestData: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    Service to handle chat session operations.
    Uses chat_session_id as the primary key.
    If the document exists, fetch it; otherwise, create a new one.
    
    Args:
        requestData: The request data containing chat session information.
    
    Returns:
        Dict containing the chat session document, or None if error.
    """
    try:
        chat_session_id = requestData.get("chat_session_id")
        agent_id = requestData.get("agent_id")

        if not chat_session_id:
            logger.warning("chat_session_id missing in requestData")
            return None

        collection = get_collection("atlas_chat_sessions")

        # Try to find existing document by chat_session_id and agent_id
        document = await collection.find_one({"chat_session_id": chat_session_id, "agent_id": agent_id})
        if document:
            # Convert ObjectId and datetime fields
            document["_id"] = str(document["_id"])
            if "created_at" in document and document["created_at"]:
                document["created_at"] = document["created_at"].isoformat()
            if "last_message_at" in document and document["last_message_at"]:
                document["last_message_at"] = document["last_message_at"].isoformat()
            
            logger.info(f"Retrieved existing chat session document for chat_session_id: {chat_session_id} and agent_id: {agent_id}")
            return document
        else:
            # Create new document
            init_config = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("chat_session_init_config", {})
            document = init_config.copy()
            
            # Set chat_session_id and agent_id in the document
            document["chat_session_id"] = chat_session_id
            document["agent_id"] = agent_id
            
            # Populate the document with data from requestData
            agent_display_name = await get_agent_alias_name(agent_id)
            channel = get_channel_from_session_id(chat_session_id)
            update_dict = {
                "agent_name": agent_display_name,
                "channel": channel,
                "created_at": datetime.now(timezone.utc),
                "last_message_at": datetime.now(timezone.utc),
            }
            source = requestData.get("source")
            if source:
                update_dict["source"] = source
            document.update(update_dict)
            
            result = await collection.insert_one(document)
            document["_id"] = str(result.inserted_id)
            document["created_at"] = document["created_at"].isoformat()
            document["last_message_at"] = document["last_message_at"].isoformat()
            
            logger.info(f"Created new chat session document with chat_session_id: {chat_session_id} and agent_id: {agent_id}")
            return document

    except Exception as e:
        logger.error(f"Error in get_chat_session_data: {str(e)}")
        return None


async def get_agent_alias_name(agent_id: str) -> str | None:
    """
    Get the display name for an agent, preferring a random alias if available.
    
    Args:
        agent_id: The ID of the agent.
    
    Returns:
        The alias name if aliases exist, otherwise the agent_name, or None if error.
    """
    try:
        if not agent_id:
            logger.warning("agent_id is required")
            return None
        
        collection = get_collection("atlas_agents")
        
        # Convert agent_id to ObjectId if it's a string
        if isinstance(agent_id, str):
            agent_id = ObjectId(agent_id)
        
        agent_doc = await collection.find_one({"_id": agent_id})
        if not agent_doc:
            logger.warning(f"Agent not found for agent_id: {agent_id}")
            return None
        
        agent_name = agent_doc.get("agent_name")
        agent_aliases = agent_doc.get("agent_aliases", [])
        
        if agent_aliases and isinstance(agent_aliases, list) and len(agent_aliases) > 0:
            # Pick a random alias
            alias = random.choice(agent_aliases)
            logger.info(f"Selected random alias '{alias}' for agent_id: {agent_id}")
            return alias
        else:
            # Return the agent_name
            logger.info(f"Using agent_name '{agent_name}' for agent_id: {agent_id}")
            return agent_name
    
    except Exception as e:
        logger.error(f"Error in get_agent_alias_name for agent_id {agent_id}: {str(e)}")
        return None


def get_channel_from_session_id(chat_session_id: str) -> str:
    """
    Extract the channel prefix from chat_session_id.
    
    Args:
        chat_session_id: The chat session ID string.
    
    Returns:
        The prefix before the first '-', or 'un' if no '-' found.
    """
    if not chat_session_id:
        return "un"
    
    if "-" in chat_session_id:
        return chat_session_id.split("-", 1)[0]
    else:
        return "un"
