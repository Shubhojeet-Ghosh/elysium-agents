
from typing import Dict, Any, Optional
from logging_config import get_logger
from services.elysium_atlas_services.atlas_url_index_services import index_agent_urls
from services.elysium_atlas_services.atlas_qdrant_services import remove_all_qdrant_agent_points
from services.mongo_services import get_collection
from datetime import datetime, timezone
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from bson import ObjectId
from services.elysium_atlas_services.agent_db_operations import update_agent_status, update_agent_fields,update_agent_current_task
from services.web_services.url_services import normalize_url
from services.elysium_atlas_services.atlas_files_index_services import index_agent_files
from services.elysium_atlas_services.atlas_custom_knowledge_services import index_custom_knowledge_for_agent
import asyncio

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
        # logger.info(f"Initializing agent build/update with request data: {requestData}")
        
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

        # Set agent status to 'indexing' after creation/update
        await update_agent_status(agent_id, "indexing")
        
        base_url = requestData.get("base_url")
        if(base_url):
            base_url = normalize_url(base_url)
            requestData["base_url"] = base_url
            update_result = await update_agent_fields(agent_id, {"base_url": base_url})

        ### Process the links for the agent
        links = requestData.get("links")

        ### Index the links for the agent in DB
        if(links):
            link_index_result = await index_agent_urls(agent_id, links)
            if not link_index_result:
                logger.error("Failed to index agent URLs")

        ### End of processing the links for the agent

        ### Process the files for the agent
        files = requestData.get("files")
        if(files):
            files_index_result = await index_agent_files(agent_id, files)
            if not files_index_result:
                logger.error("Failed to index agent files")

        ### End of processing the files for the agent

        ### Extract custom texts for the agent
        custom_texts = requestData.get("custom_texts")

        ### Extract custom Q&As for the agent
        qa_pairs = requestData.get("qa_pairs")

        if custom_texts or qa_pairs:
            custom_texts_result = await index_custom_knowledge_for_agent(agent_id, custom_texts, qa_pairs)
            if not custom_texts_result:
                logger.error("Failed to store custom texts/QA pairs for agent")
        
        ### End of extracting custom texts for the agent

        await update_agent_current_task(agent_id, "running")
        # Set agent status to 'active' just before returning True
        await update_agent_status(agent_id, "active")
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

        # Call the remove functions for related data
        urls_deleted_count = await remove_agent_urls(agent_id)
        files_deleted_count = await remove_agent_files(agent_id)
        custom_texts_deleted_count = await remove_agent_custom_texts(agent_id)
        qa_pairs_deleted_count = await remove_agent_qa_pairs(agent_id)

        if agent_result.deleted_count == 1:
            logger.info(f"Successfully removed agent with ID: {agent_id}")
            logger.info(f"Successfully removed {urls_deleted_count} related links, {files_deleted_count} files, {custom_texts_deleted_count} custom texts, and {qa_pairs_deleted_count} QA pairs for agent ID: {agent_id}")
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

async def remove_agent_files(agent_id: str) -> int:
    """
    Remove all file documents related to the given agent_id from the 'atlas_agent_files' collection.

    Args:
        agent_id: The ID of the agent whose related files are to be removed.

    Returns:
        int: The number of file documents removed.
    """
    try:
        files_collection = get_collection("atlas_agent_files")
 
        # Attempt to delete all related files for the agent
        files_result = await files_collection.delete_many({"agent_id": agent_id})
        
        logger.info(f"Successfully removed {files_result.deleted_count} related files for agent ID: {agent_id}")
        
        return files_result.deleted_count

    except Exception as e:
        logger.error(f"Error removing files for agent ID {agent_id}: {e}")
        return 0

async def remove_agent_custom_texts(agent_id: str) -> int:
    """
    Remove all custom text documents related to the given agent_id from the 'atlas_custom_texts' collection.

    Args:
        agent_id: The ID of the agent whose related custom texts are to be removed.

    Returns:
        int: The number of custom text documents removed.
    """
    try:
        custom_texts_collection = get_collection("atlas_custom_texts")
 
        # Attempt to delete all related custom texts for the agent
        custom_texts_result = await custom_texts_collection.delete_many({"agent_id": agent_id})
        
        logger.info(f"Successfully removed {custom_texts_result.deleted_count} related custom texts for agent ID: {agent_id}")
        
        return custom_texts_result.deleted_count

    except Exception as e:
        logger.error(f"Error removing custom texts for agent ID {agent_id}: {e}")
        return 0

async def remove_agent_qa_pairs(agent_id: str) -> int:
    """
    Remove all QA pair documents related to the given agent_id from the 'atlas_qa_pairs' collection.

    Args:
        agent_id: The ID of the agent whose related QA pairs are to be removed.

    Returns:
        int: The number of QA pair documents removed.
    """
    try:
        qa_pairs_collection = get_collection("atlas_qa_pairs")
 
        # Attempt to delete all related QA pairs for the agent
        qa_pairs_result = await qa_pairs_collection.delete_many({"agent_id": agent_id})
        
        logger.info(f"Successfully removed {qa_pairs_result.deleted_count} related QA pairs for agent ID: {agent_id}")
        
        return qa_pairs_result.deleted_count

    except Exception as e:
        logger.error(f"Error removing QA pairs for agent ID {agent_id}: {e}")
        return 0

async def fetch_agent_document(agent_id: str) -> Optional[Dict[str, Any]]:
    try:
        collection = get_collection("atlas_agents")
        document = await collection.find_one({"_id": ObjectId(agent_id)})
        if document:
            # Convert _id to string and set as agent_id
            document["agent_id"] = str(document.pop("_id"))
            
            # Convert datetime fields to strings
            if "created_at" in document and document["created_at"] and isinstance(document["created_at"], datetime):
                document["created_at"] = document["created_at"].isoformat()
            if "updated_at" in document and document["updated_at"] and isinstance(document["updated_at"], datetime):
                document["updated_at"] = document["updated_at"].isoformat()
            
            return document
        else:
            logger.warning(f"No agent found with ID: {agent_id}")
            return None
    except Exception as e:
        logger.error(f"Error fetching agent document for agent_id {agent_id}: {e}")
        return None

async def fetch_agent_urls(agent_id: str) -> list[Dict[str, Any]]:
    try:
        urls_collection = get_collection("atlas_agent_urls")
        urls_cursor = urls_collection.find({"agent_id": agent_id})
        urls = []
        async for url_doc in urls_cursor:
            url_doc.pop("_id", None)
            if "created_at" in url_doc and url_doc["created_at"] and isinstance(url_doc["created_at"], datetime):
                url_doc["created_at"] = url_doc["created_at"].isoformat()
            if "updated_at" in url_doc and url_doc["updated_at"] and isinstance(url_doc["updated_at"], datetime):
                url_doc["updated_at"] = url_doc["updated_at"].isoformat()
            urls.append(url_doc)
        logger.info(f"Fetched {len(urls)} URLs for agent_id {agent_id}")
        return urls
    except Exception as e:
        logger.error(f"Error fetching URLs for agent_id {agent_id}: {e}")
        return []

async def fetch_agent_files(agent_id: str) -> list[Dict[str, Any]]:
    try:
        files_collection = get_collection("atlas_agent_files")
        files_cursor = files_collection.find({"agent_id": agent_id})
        files = []
        async for file_doc in files_cursor:
            file_doc.pop("_id", None)
            if "created_at" in file_doc and file_doc["created_at"] and isinstance(file_doc["created_at"], datetime):
                file_doc["created_at"] = file_doc["created_at"].isoformat()
            if "updated_at" in file_doc and file_doc["updated_at"] and isinstance(file_doc["updated_at"], datetime):
                file_doc["updated_at"] = file_doc["updated_at"].isoformat()
            files.append(file_doc)
        logger.info(f"Fetched {len(files)} files for agent_id {agent_id}")
        return files
    except Exception as e:
        logger.error(f"Error fetching files for agent_id {agent_id}: {e}")
        return []

async def fetch_agent_custom_knowledge(agent_id: str) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    try:
        # Fetch all custom texts for the agent
        custom_texts_collection = get_collection("atlas_custom_texts")
        custom_texts_cursor = custom_texts_collection.find({"agent_id": agent_id})
        custom_texts = []
        async for ct_doc in custom_texts_cursor:
            ct_doc.pop("_id", None)
            if "created_at" in ct_doc and ct_doc["created_at"] and isinstance(ct_doc["created_at"], datetime):
                ct_doc["created_at"] = ct_doc["created_at"].isoformat()
            if "updated_at" in ct_doc and ct_doc["updated_at"] and isinstance(ct_doc["updated_at"], datetime):
                ct_doc["updated_at"] = ct_doc["updated_at"].isoformat()
            custom_texts.append(ct_doc)
        
        # Fetch all QA pairs for the agent
        qa_pairs_collection = get_collection("atlas_qa_pairs")
        qa_pairs_cursor = qa_pairs_collection.find({"agent_id": agent_id})
        qa_pairs = []
        async for qa_doc in qa_pairs_cursor:
            qa_doc.pop("_id", None)
            if "created_at" in qa_doc and qa_doc["created_at"] and isinstance(qa_doc["created_at"], datetime):
                qa_doc["created_at"] = qa_doc["created_at"].isoformat()
            if "updated_at" in qa_doc and qa_doc["updated_at"] and isinstance(qa_doc["updated_at"], datetime):
                qa_doc["updated_at"] = qa_doc["updated_at"].isoformat()
            qa_pairs.append(qa_doc)
        
        logger.info(f"Fetched {len(custom_texts)} custom texts and {len(qa_pairs)} QA pairs for agent_id {agent_id}")
        return custom_texts, qa_pairs
    except Exception as e:
        logger.error(f"Error fetching custom knowledge for agent_id {agent_id}: {e}")
        return [], []

async def fetch_agent_details_by_id(agent_id: str) -> Optional[Dict[str, Any]]:
    try:
        agent_task_progress = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_task_progress", {})

        document = await fetch_agent_document(agent_id)
        if not document:
            return None
        
        agent_current_task = document.get("agent_current_task", "initializing")
        task_progress = agent_task_progress.get(agent_current_task,0)

        urls, files, custom_knowledge = await asyncio.gather(
            fetch_agent_urls(agent_id),
            fetch_agent_files(agent_id),
            fetch_agent_custom_knowledge(agent_id)
        )
        
        custom_texts, qa_pairs = custom_knowledge
        
        document["progress"] = task_progress
        document["links"] = urls
        document["files"] = files
        document["custom_texts"] = custom_texts
        document["qa_pairs"] = qa_pairs
        
        return document
    except Exception as e:
        logger.error(f"Error fetching agent details for agent_id {agent_id}: {e}")
        return None