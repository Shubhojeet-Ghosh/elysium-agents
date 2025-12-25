from typing import Dict, Any, Optional
from logging_config import get_logger
from services.elysium_atlas_services.atlas_url_index_services import index_agent_urls
from services.elysium_atlas_services.atlas_qdrant_services import remove_all_qdrant_agent_points
from services.mongo_services import get_collection
from datetime import datetime, timezone
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from bson import ObjectId

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

async def list_agents_for_user(user_id: str) -> list[dict]:
    """
    List all agents for a given user_id, including their basic data and progress.

    Args:
        user_id: The ID of the user whose agents are to be listed.

    Returns:
        list[dict]: A list of dictionaries containing agent details.
    """
    try:
        collection = get_collection("atlas_agents")

        agent_task_progress = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_task_progress", {})

        # Query to find agents for the given user_id, sorted by updated_at in descending order
        agents_cursor = collection.find({"owner_user_id": user_id}).sort("updated_at", -1)

        agents = []
        async for agent in agents_cursor:
            agent_id = str(agent.get("_id"))
            agent_name = agent.get("agent_name", "Unknown")
            agent_icon = agent.get("agent_icon", None)
            agent_status = agent.get("agent_status", "inactive")
            agent_current_task = agent.get("agent_current_task", "initializing")
            created_at = agent.get("created_at").isoformat() if agent.get("created_at") else None
            updated_at = agent.get("updated_at").isoformat() if agent.get("updated_at") else None

            # Calculate progress based on agent_current_task and agent_task_progress
            task_progress = agent_task_progress.get(agent_current_task)

            agents.append({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "agent_icon": agent_icon,
                "agent_status": agent_status,
                "agent_current_task": agent_current_task,
                "progress": task_progress,
                "created_at": created_at,
                "updated_at": updated_at
            })

        logger.info(f"Listed {len(agents)} agents for user_id: {user_id}")
        return agents

    except Exception as e:
        logger.error(f"Error listing agents for user_id {user_id}: {e}")
        return []

async def remove_agent_by_id(agent_id: str) -> bool:
    """
    Remove an agent from the 'atlas_agents' collection by its ID and all related links from the 'atlas_agent_urls' collection.

    Args:
        agent_id: The ID of the agent to be removed.

    Returns:
        bool: True if the agent and its related links were successfully removed, False otherwise.
    """
    try:
        collection = get_collection("atlas_agents")
        
        # Attempt to delete the agent with the given agent_id
        agent_result = await collection.delete_one({"_id": ObjectId(agent_id)})

        # Call the remove_agent_urls function to delete related links
        urls_deleted_count = await remove_agent_urls(agent_id)

        if agent_result.deleted_count == 1:
            logger.info(f"Successfully removed agent with ID: {agent_id}")
            logger.info(f"Successfully removed {urls_deleted_count} related links for agent ID: {agent_id}")
            return True
        else:
            logger.warning(f"No agent found with ID: {agent_id} to remove.")
            return False

    except Exception as e:
        logger.error(f"Error removing agent with ID {agent_id}: {e}")
        return False

async def remove_agent_urls(agent_id: str) -> int:
    """
    Remove all URL documents related to the given agent_id from the 'atlas_agent_urls' collection.

    Args:
        agent_id: The ID of the agent whose related URLs are to be removed.

    Returns:
        int: The number of URL documents removed.
    """
    try:
        urls_collection = get_collection("atlas_agent_urls")
 
        # Attempt to delete all related links for the agent
        urls_result = await urls_collection.delete_many({"agent_id": agent_id})
        
        logger.info(f"Successfully removed {urls_result.deleted_count} related links for agent ID: {agent_id}")
        
        remove_result = await remove_all_qdrant_agent_points(agent_id)
        
        return urls_result.deleted_count

    except Exception as e:
        logger.error(f"Error removing URLs for agent ID {agent_id}: {e}")
        return 0

