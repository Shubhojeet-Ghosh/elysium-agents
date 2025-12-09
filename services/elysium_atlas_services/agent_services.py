from typing import Dict, Any, Optional
from logging_config import get_logger
from services.elysium_atlas_services.atlas_url_index_services import index_agent_urls
from services.mongo_services import get_collection
from datetime import datetime, timezone

logger = get_logger()

async def create_agent_document() -> Optional[str]:
    """
    Initialize a new agent document in the 'atlas_agents' collection.
    Creates a document with only created_at and updated_at fields (plus default _id).
    This is the first step in building an agent - the document can be updated later using the returned _id.
    
    Returns:
        str: The _id of the created document, or None if creation failed
    """
    try:
        collection = get_collection("atlas_agents")
        current_time = datetime.now(timezone.utc)
        
        document = {
            "created_at": current_time,
            "updated_at": current_time
        }
        
        result = await collection.insert_one(document)
        agent_id = str(result.inserted_id)
        logger.info(f"Created agent document with _id: {agent_id}")
        return agent_id
        
    except Exception as e:
        logger.error(f"Error creating agent document: {e}")
        return None

async def initialize_agent_build(requestData: Dict[str, Any]) -> bool:
    try:
        logger.info(f"Initializing agent build with request data: {requestData}")
        
        agent_id = requestData.get("agent_id")

        if not agent_id:
            agent_id = await create_agent_document()
            if not agent_id:
                logger.error("Failed to create agent document")
                return False

        links = requestData.get("links")

        # Store links in MongoDB
        link_index_result = await index_agent_urls(agent_id,links)
        if not link_index_result:
            logger.error("Failed to store agent URLs")
            return False
        
        return True
    except Exception as e:
        logger.error(f"Error storing agent URLs: {e}")
        return False

