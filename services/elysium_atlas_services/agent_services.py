from typing import Dict, Any, Optional
from logging_config import get_logger
from services.elysium_atlas_services.atlas_url_index_services import index_agent_urls
from services.mongo_services import get_collection
from datetime import datetime, timezone

logger = get_logger()

async def create_agent_document(initial_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Initialize a new agent document in the 'atlas_agents' collection.
    Creates a document with created_at and updated_at fields (plus default _id).
    If initial_data is provided, all key-value pairs from it will be included in the document.
    This is the first step in building an agent - the document can be updated later using the returned _id.
    
    Args:
        initial_data: Optional dictionary containing initial fields to include in the document.
                     If None, only created_at and updated_at will be included.
    
    Returns:
        str: The _id of the created document, or None if creation failed
    """
    try:
        collection = get_collection("atlas_agents")
        current_time = datetime.now(timezone.utc)
        
        document = dict[Any, Any]()
        
        # If initial_data is provided, merge all key-value pairs into the document
        if initial_data is not None:
            document.update(initial_data)
        
        document["created_at"] = current_time
        document["updated_at"] = current_time

        result = await collection.insert_one(document)
        agent_id = str(result.inserted_id)
        logger.info(f"Created agent document with _id: {agent_id}")
        return agent_id
        
    except Exception as e:
        logger.error(f"Error creating agent document: {e}")
        return None

async def initialize_agent_build_update(requestData: Dict[str, Any]) -> bool:
    try:
        logger.info(f"Initializing agent build/update with request data: {requestData}")
        
        agent_id = requestData.get("agent_id")
        
        operation = "build"
        if not agent_id:
            agent_id = await create_agent_document()
            operation = "build"
            if not agent_id:
                logger.error("Failed to create agent document")
                return False
        else:
            operation = "update"
        requestData["operation"] = operation
        
        ### Process the links for the agent
        links = requestData.get("links")

        ### Index the links for the agent in DB
        link_index_result = await index_agent_urls(agent_id,links)
        if not link_index_result:
            logger.error("Failed to store agent URLs")
            return False
        
        ### End of processing the links for the agent

        ### Process the files for the agent
        files = requestData.get("files")
        ### End of processing the files for the agent

        ### Extract custom texts for the agent
        custom_texts = requestData.get("custom_text_list")
        ### End of extracting custom texts

        ### Extract custom Q&As for the agent
        qa_pairs = requestData.get("qa_pairs")
        ### End of extracting custom Q&As


        return True
    except Exception as e:
        logger.error(f"Error storing agent URLs: {e}")
        return False

