
from typing import Dict, Any, Optional
from logging_config import get_logger
from services.elysium_atlas_services.atlas_url_index_services import index_agent_urls
from services.elysium_atlas_services.atlas_qdrant_services import remove_all_qdrant_agent_points
from services.mongo_services import get_collection
from datetime import datetime, timezone
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from bson import ObjectId
from services.elysium_atlas_services.agent_db_operations import update_agent_status, update_agent_fields,update_agent_current_task, get_agent_by_id, get_agent_fields_by_id
from services.web_services.url_services import normalize_url
from services.elysium_atlas_services.atlas_files_index_services import index_agent_files
from services.elysium_atlas_services.atlas_custom_knowledge_services import index_custom_knowledge_for_agent
import asyncio
from config.settings import settings
from services.qdrant_api_services import delete_qdrant_points_by_filter
from services.elysium_atlas_services.qdrant_collection_helpers import (
    AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
    AGENT_WEB_CATALOG_COLLECTION_NAME
)

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

        document["agent_status"] = "active"
        document["agent_current_task"] = "running"

        result = await collection.insert_one(document)
        agent_id = str(result.inserted_id)

        await generate_agent_widget_script(agent_id)
        
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

        await generate_agent_widget_script(agent_id)

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
        files_deleted_count = await remove_all_agent_files(agent_id)
        custom_texts_deleted_count = await remove_agent_custom_texts(agent_id)
        qa_pairs_deleted_count = await remove_agent_qa_pairs(agent_id)

        return True

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

async def remove_all_agent_files(agent_id: str) -> int:
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

async def fetch_agent_urls(
    agent_id: str,
    limit: int = 50,
    cursor: Optional[str] = None,
    include_count: bool = False
) -> Dict[str, Any]:
    """
    Fetch URLs for an agent with cursor-based pagination.
    
    Args:
        agent_id: The agent ID to fetch URLs for
        limit: Number of items per page (default 50, max 100)
        cursor: Pagination cursor (the _id of the last item from previous page)
        include_count: Whether to include total count (expensive, only use on first request)
    
    Returns:
        Dict with keys: data, next_cursor, has_more, total_count (if include_count=True)
    """
    try:
        urls_collection = get_collection("atlas_agent_urls")
        
        # Enforce max limit
        limit = min(limit, 100)
        
        # Build query
        query: Dict[str, Any] = {"agent_id": agent_id}
        
        # Parse cursor for pagination
        if cursor:
            try:
                # Fetch the cursor document to get its updated_at value
                cursor_doc = await urls_collection.find_one({"_id": ObjectId(cursor)})
                if cursor_doc:
                    cursor_updated_at = cursor_doc.get("updated_at")
                    
                    # Compound condition: items with earlier updated_at OR same updated_at but earlier _id
                    query["$or"] = [
                        {"updated_at": {"$lt": cursor_updated_at}},
                        {
                            "updated_at": cursor_updated_at,
                            "_id": {"$lt": ObjectId(cursor)}
                        }
                    ]
            except Exception as e:
                logger.warning(f"Invalid cursor format: {cursor}, error: {e}")
        
        # Fetch limit + 1 to determine if there are more items
        urls_cursor = urls_collection.find(query).sort([("updated_at", -1), ("_id", -1)]).limit(limit + 1)
        
        urls = []
        last_id = None
        async for url_doc in urls_cursor:
            # Store _id before converting
            doc_id = str(url_doc["_id"])
            last_id = doc_id
            url_doc.pop("_id", None)
            
            if "created_at" in url_doc and url_doc["created_at"] and isinstance(url_doc["created_at"], datetime):
                url_doc["created_at"] = url_doc["created_at"].isoformat()
            if "updated_at" in url_doc and url_doc["updated_at"] and isinstance(url_doc["updated_at"], datetime):
                url_doc["updated_at"] = url_doc["updated_at"].isoformat()
            
            urls.append(url_doc)
        
        # Check if there are more items
        has_more = len(urls) > limit
        if has_more:
            urls = urls[:limit]  # Remove the extra item
            # Update last_id to be the last item in the trimmed list
            if urls:
                # Re-fetch the _id from the collection since we already popped it
                last_item_updated_at = urls[-1].get("updated_at")
                last_item_doc = await urls_collection.find_one(
                    {"agent_id": agent_id, "updated_at": datetime.fromisoformat(last_item_updated_at.replace('Z', '+00:00'))},
                    sort=[("updated_at", -1), ("_id", -1)]
                )
                if last_item_doc:
                    last_id = str(last_item_doc["_id"])
        
        # Generate next cursor from last item (just the _id)
        next_cursor = last_id if (urls and has_more) else None
        
        # Get total count only if requested (expensive operation)
        result: Dict[str, Any] = {
            "data": urls,
            "next_cursor": next_cursor,
            "has_more": has_more
        }
        
        if include_count:
            total_count = await urls_collection.count_documents({"agent_id": agent_id})
            result["total_count"] = total_count
        
        logger.info(f"Fetched {len(urls)} URLs for agent_id {agent_id}, has_more: {has_more}")
        return result
        
    except Exception as e:
        logger.error(f"Error fetching URLs for agent_id {agent_id}: {e}")
        return {"data": [], "next_cursor": None, "has_more": False}

async def fetch_agent_files(
    agent_id: str,
    limit: int = 50,
    cursor: Optional[str] = None,
    include_count: bool = False
) -> Dict[str, Any]:
    """
    Fetch files for an agent with cursor-based pagination.
    
    Args:
        agent_id: The agent ID to fetch files for
        limit: Number of items per page (default 50, max 100)
        cursor: Pagination cursor (the _id of the last item from previous page)
        include_count: Whether to include total count (expensive, only use on first request)
    
    Returns:
        Dict with keys: data, next_cursor, has_more, total_count (if include_count=True)
    """
    try:
        files_collection = get_collection("atlas_agent_files")
        
        # Enforce max limit
        limit = min(limit, 100)
        
        # Build query
        query: Dict[str, Any] = {"agent_id": agent_id}
        
        # Parse cursor for pagination
        if cursor:
            try:
                # Fetch the cursor document to get its updated_at value
                cursor_doc = await files_collection.find_one({"_id": ObjectId(cursor)})
                if cursor_doc:
                    cursor_updated_at = cursor_doc.get("updated_at")
                    
                    query["$or"] = [
                        {"updated_at": {"$lt": cursor_updated_at}},
                        {
                            "updated_at": cursor_updated_at,
                            "_id": {"$lt": ObjectId(cursor)}
                        }
                    ]
            except Exception as e:
                logger.warning(f"Invalid cursor format: {cursor}, error: {e}")
        
        files_cursor = files_collection.find(query).sort([("updated_at", -1), ("_id", -1)]).limit(limit + 1)
        
        files = []
        last_id = None
        async for file_doc in files_cursor:
            doc_id = str(file_doc["_id"])
            last_id = doc_id
            file_doc.pop("_id", None)
            
            if "created_at" in file_doc and file_doc["created_at"] and isinstance(file_doc["created_at"], datetime):
                file_doc["created_at"] = file_doc["created_at"].isoformat()
            if "updated_at" in file_doc and file_doc["updated_at"] and isinstance(file_doc["updated_at"], datetime):
                file_doc["updated_at"] = file_doc["updated_at"].isoformat()
            
            files.append(file_doc)
        
        has_more = len(files) > limit
        if has_more:
            files = files[:limit]
            if files:
                last_item_updated_at = files[-1].get("updated_at")
                last_item_doc = await files_collection.find_one(
                    {"agent_id": agent_id, "updated_at": datetime.fromisoformat(last_item_updated_at.replace('Z', '+00:00'))},
                    sort=[("updated_at", -1), ("_id", -1)]
                )
                if last_item_doc:
                    last_id = str(last_item_doc["_id"])
        
        next_cursor = last_id if (files and has_more) else None
        
        result: Dict[str, Any] = {
            "data": files,
            "next_cursor": next_cursor,
            "has_more": has_more
        }
        
        if include_count:
            total_count = await files_collection.count_documents({"agent_id": agent_id})
            result["total_count"] = total_count
        
        logger.info(f"Fetched {len(files)} files for agent_id {agent_id}, has_more: {has_more}")
        return result
        
    except Exception as e:
        logger.error(f"Error fetching files for agent_id {agent_id}: {e}")
        return {"data": [], "next_cursor": None, "has_more": False}

async def fetch_agent_custom_knowledge(
    agent_id: str,
    limit: int = 50,
    cursor: Optional[str] = None,
    include_count: bool = False
) -> Dict[str, Any]:
    """
    Fetch custom knowledge (texts and QA pairs) for an agent with cursor-based pagination.
    
    Args:
        agent_id: The agent ID to fetch custom knowledge for
        limit: Number of items per page (default 50, max 100)
        cursor: Pagination cursor (the _id of the last item from previous page)
        include_count: Whether to include total counts (expensive, only use on first request)
    
    Returns:
        Dict with keys: custom_texts, qa_pairs, each containing {data, next_cursor, has_more, total_count}
    """
    try:
        limit = min(limit, 100)
        
        # Fetch custom texts
        custom_texts_collection = get_collection("atlas_custom_texts")
        ct_query: Dict[str, Any] = {"agent_id": agent_id}
        
        if cursor:
            try:
                cursor_doc = await custom_texts_collection.find_one({"_id": ObjectId(cursor)})
                if cursor_doc:
                    cursor_updated_at = cursor_doc.get("updated_at")
                    
                    ct_query["$or"] = [
                        {"updated_at": {"$lt": cursor_updated_at}},
                        {"updated_at": cursor_updated_at, "_id": {"$lt": ObjectId(cursor)}}
                    ]
            except Exception as e:
                logger.warning(f"Invalid cursor format: {cursor}, error: {e}")
        
        ct_cursor = custom_texts_collection.find(ct_query).sort([("updated_at", -1), ("_id", -1)]).limit(limit + 1)
        custom_texts = []
        ct_last_id = None
        async for ct_doc in ct_cursor:
            doc_id = str(ct_doc["_id"])
            ct_last_id = doc_id
            ct_doc.pop("_id", None)
            
            if "created_at" in ct_doc and ct_doc["created_at"] and isinstance(ct_doc["created_at"], datetime):
                ct_doc["created_at"] = ct_doc["created_at"].isoformat()
            if "updated_at" in ct_doc and ct_doc["updated_at"] and isinstance(ct_doc["updated_at"], datetime):
                ct_doc["updated_at"] = ct_doc["updated_at"].isoformat()
            
            custom_texts.append(ct_doc)
        
        ct_has_more = len(custom_texts) > limit
        if ct_has_more:
            custom_texts = custom_texts[:limit]
            if custom_texts:
                last_item_updated_at = custom_texts[-1].get("updated_at")
                last_item_doc = await custom_texts_collection.find_one(
                    {"agent_id": agent_id, "updated_at": datetime.fromisoformat(last_item_updated_at.replace('Z', '+00:00'))},
                    sort=[("updated_at", -1), ("_id", -1)]
                )
                if last_item_doc:
                    ct_last_id = str(last_item_doc["_id"])
        
        ct_next_cursor = ct_last_id if (custom_texts and ct_has_more) else None
        
        # Fetch QA pairs
        qa_pairs_collection = get_collection("atlas_qa_pairs")
        qa_query: Dict[str, Any] = {"agent_id": agent_id}
        
        if cursor:
            try:
                cursor_doc = await qa_pairs_collection.find_one({"_id": ObjectId(cursor)})
                if cursor_doc:
                    cursor_updated_at = cursor_doc.get("updated_at")
                    
                    qa_query["$or"] = [
                        {"updated_at": {"$lt": cursor_updated_at}},
                        {"updated_at": cursor_updated_at, "_id": {"$lt": ObjectId(cursor)}}
                    ]
            except Exception as e:
                logger.warning(f"Invalid cursor format: {cursor}, error: {e}")
        
        qa_cursor = qa_pairs_collection.find(qa_query).sort([("updated_at", -1), ("_id", -1)]).limit(limit + 1)
        qa_pairs = []
        qa_last_id = None
        async for qa_doc in qa_cursor:
            doc_id = str(qa_doc["_id"])
            qa_last_id = doc_id
            qa_doc.pop("_id", None)
            
            if "created_at" in qa_doc and qa_doc["created_at"] and isinstance(qa_doc["created_at"], datetime):
                qa_doc["created_at"] = qa_doc["created_at"].isoformat()
            if "updated_at" in qa_doc and qa_doc["updated_at"] and isinstance(qa_doc["updated_at"], datetime):
                qa_doc["updated_at"] = qa_doc["updated_at"].isoformat()
            
            qa_pairs.append(qa_doc)
        
        qa_has_more = len(qa_pairs) > limit
        if qa_has_more:
            qa_pairs = qa_pairs[:limit]
            if qa_pairs:
                last_item_updated_at = qa_pairs[-1].get("updated_at")
                last_item_doc = await qa_pairs_collection.find_one(
                    {"agent_id": agent_id, "updated_at": datetime.fromisoformat(last_item_updated_at.replace('Z', '+00:00'))},
                    sort=[("updated_at", -1), ("_id", -1)]
                )
                if last_item_doc:
                    qa_last_id = str(last_item_doc["_id"])
        
        qa_next_cursor = qa_last_id if (qa_pairs and qa_has_more) else None
        
        result: Dict[str, Any] = {
            "custom_texts": {
                "data": custom_texts,
                "next_cursor": ct_next_cursor,
                "has_more": ct_has_more
            },
            "qa_pairs": {
                "data": qa_pairs,
                "next_cursor": qa_next_cursor,
                "has_more": qa_has_more
            }
        }
        
        if include_count:
            ct_count = await custom_texts_collection.count_documents({"agent_id": agent_id})
            qa_count = await qa_pairs_collection.count_documents({"agent_id": agent_id})
            result["custom_texts"]["total_count"] = ct_count
            result["qa_pairs"]["total_count"] = qa_count
        
        logger.info(f"Fetched {len(custom_texts)} custom texts and {len(qa_pairs)} QA pairs for agent_id {agent_id}")
        return result
        
    except Exception as e:
        logger.error(f"Error fetching custom knowledge for agent_id {agent_id}: {e}")
        return {
            "custom_texts": {"data": [], "next_cursor": None, "has_more": False},
            "qa_pairs": {"data": [], "next_cursor": None, "has_more": False}
        }

async def fetch_agent_details_by_id(
    agent_id: str,
    urls_limit: int = 50,
    urls_cursor: Optional[str] = None,
    files_limit: int = 50,
    files_cursor: Optional[str] = None,
    custom_limit: int = 50,
    custom_cursor: Optional[str] = None,
    include_counts: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Fetch complete agent details including paginated related data.
    
    Args:
        agent_id: The agent ID
        urls_limit: Limit for URLs pagination
        urls_cursor: Cursor for URLs pagination
        files_limit: Limit for files pagination
        files_cursor: Cursor for files pagination
        custom_limit: Limit for custom knowledge pagination
        custom_cursor: Cursor for custom knowledge pagination
        include_counts: Whether to include total counts (use True on first request)
    
    Returns:
        Agent document with paginated links, files, custom_texts, and qa_pairs
    """
    try:
        agent_task_progress = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_task_progress", {})

        document = await fetch_agent_document(agent_id)
        if not document:
            return None
        
        agent_current_task = document.get("agent_current_task", "initializing")
        task_progress = agent_task_progress.get(agent_current_task, 0)

        # Fetch paginated data in parallel
        urls_result, files_result, custom_knowledge_result = await asyncio.gather(
            fetch_agent_urls(agent_id, limit=urls_limit, cursor=urls_cursor, include_count=include_counts),
            fetch_agent_files(agent_id, limit=files_limit, cursor=files_cursor, include_count=include_counts),
            fetch_agent_custom_knowledge(agent_id, limit=custom_limit, cursor=custom_cursor, include_count=include_counts)
        )
        
        document["progress"] = task_progress
        document["links"] = urls_result
        document["files"] = files_result
        document["custom_texts"] = custom_knowledge_result["custom_texts"]
        document["qa_pairs"] = custom_knowledge_result["qa_pairs"]
        
        return document
    except Exception as e:
        logger.error(f"Error fetching agent details for agent_id {agent_id}: {e}")
        return None

async def initialize_agent_update(requestData: Dict[str, Any]) -> bool:
    try:
        # logger.info(f"Initializing agent build/update with request data: {requestData}")
        
        agent_id = requestData.get("agent_id")
        
        operation = "update"
        requestData["operation"] = operation

        if not agent_id:
            logger.error("agent_id is required for update operation")
            return False
        
        logger.info(f"Updating agent with ID: {agent_id}")

        # Set agent status to 'indexing' after creation/update
        await update_agent_status(agent_id, "updating")
        
        await update_agent_current_task(agent_id, "updating agent metadata")
        
        agent_icon = requestData.get("agent_icon")
        if agent_icon is not None:
            await update_agent_fields(agent_id, {"agent_icon": agent_icon})
            
        updates = {}
        
        base_url = requestData.get("base_url")
        if(base_url):
            base_url = normalize_url(base_url)
            requestData["base_url"] = base_url
            updates["base_url"] = base_url

        agent_name = requestData.get("agent_name")
        if(agent_name is not None):
            updates["agent_name"] = agent_name

        system_prompt = requestData.get("system_prompt")
        if(system_prompt is not None):
            updates["system_prompt"] = system_prompt

        welcome_message = requestData.get("welcome_message")
        if(welcome_message is not None):
            updates["welcome_message"] = welcome_message

        llm_model = requestData.get("llm_model")
        if(llm_model is not None):
            updates["llm_model"] = llm_model

        temperature = requestData.get("temperature")
        if isinstance(temperature, (int, float)):
            updates["temperature"] = temperature
        
        if updates:
            metadata_update_result = await update_agent_fields(agent_id, updates)
            logger.info(f"Updated metadata for agent {agent_id}: {list(updates.keys())} - success: {metadata_update_result}")
        
        await update_agent_status(agent_id, "indexing")

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

        await update_agent_current_task(agent_id, "running")

        # Set agent status to 'active' just before returning True
        await update_agent_status(agent_id, "active")
        
        logger.info(f"Successfully updated agent with ID: {agent_id}")
        return True
    
    except Exception as e:
        logger.error(f"Error updating agent URLs: {e}")
        return False


async def fetch_agent_fields_by_id(agent_id: str, fields: list[str]) -> Dict[str, Any] | None:
    """
    Fetch specific fields of an agent by ID.
    """
    return await get_agent_fields_by_id(agent_id, fields)

async def generate_agent_widget_script(agent_id: str) -> str | None:
    try:

        ELYSIUM_CDN_BASE_URL = settings.ELYSIUM_CDN_BASE_URL
        ATLAS_WIDGET_VERSION = settings.ATLAS_WIDGET_VERSION

        widget_script_url = f"{ELYSIUM_CDN_BASE_URL}/widget/{ATLAS_WIDGET_VERSION}/widget.js?agent_id={agent_id}"
        widget_script = f'<script src="{widget_script_url}"></script>'
        update_result = await update_agent_fields(agent_id, {"widget_script": widget_script})
        logger.info(f"Generated widget script for agent_id {agent_id}: {widget_script}, update success: {update_result}")
        
        return widget_script
    
    except Exception as e:
        logger.error(f"Error generating widget script for agent_id {agent_id}: {e}")
        return None

async def remove_agent_links(agent_id: str, links: list[str]) -> dict:
    """
    Remove specific links from an agent's knowledge base (MongoDB and Qdrant).
    
    Args:
        agent_id: The ID of the agent
        links: List of URLs to remove (knowledge_source values)
    
    Returns:
        dict: Result with success status, counts, and errors
    """
    try:
        mongodb_deleted = 0
        qdrant_result = {
            "knowledge_base_deleted": 0,
            "web_catalog_deleted": 0
        }
        errors = []
        
        # Remove from MongoDB atlas_agent_urls collection
        try:
            urls_collection = get_collection("atlas_agent_urls")
            mongo_result = await urls_collection.delete_many({
                "agent_id": agent_id,
                "url": {"$in": links}
            })
            mongodb_deleted = mongo_result.deleted_count
            logger.info(f"Deleted {mongodb_deleted} URLs from MongoDB for agent_id {agent_id}")
        except Exception as e:
            error_msg = f"MongoDB deletion error: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
        
        # Remove from Qdrant collections
        # Build filter for Qdrant - matching agent_id AND knowledge_source in the links list
        qdrant_filters = {
            "must": [
                {"key": "agent_id", "match": {"value": agent_id}},
                {"key": "knowledge_source", "match": {"any": links}}
            ]
        }
        
        # Delete from agent_knowledge_base collection
        try:
            kb_result = await delete_qdrant_points_by_filter(
                collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                filters=qdrant_filters
            )
            if kb_result.get("success"):
                # Extract deletion count if available in result
                kb_count = kb_result.get("result", {}).get("deleted", 0) if isinstance(kb_result.get("result"), dict) else 0
                qdrant_result["knowledge_base_deleted"] = kb_count
                logger.info(f"Deleted {kb_count} points from {AGENT_KNOWLEDGE_BASE_COLLECTION_NAME} for agent_id {agent_id}")
            else:
                errors.append(f"Knowledge base deletion: {kb_result.get('message')}")
        except Exception as e:
            error_msg = f"Knowledge base Qdrant deletion error: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
        
        # Delete from agent_web_catalog collection
        try:
            wc_result = await delete_qdrant_points_by_filter(
                collection_name=AGENT_WEB_CATALOG_COLLECTION_NAME,
                filters=qdrant_filters
            )
            if wc_result.get("success"):
                # Extract deletion count if available in result
                wc_count = wc_result.get("result", {}).get("deleted", 0) if isinstance(wc_result.get("result"), dict) else 0
                qdrant_result["web_catalog_deleted"] = wc_count
                logger.info(f"Deleted {wc_count} points from {AGENT_WEB_CATALOG_COLLECTION_NAME} for agent_id {agent_id}")
            else:
                errors.append(f"Web catalog deletion: {wc_result.get('message')}")
        except Exception as e:
            error_msg = f"Web catalog Qdrant deletion error: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
        
        success = mongodb_deleted > 0 or len(errors) == 0
        
        logger.info(f"Removed {len(links)} links for agent_id {agent_id}: MongoDB={mongodb_deleted}, Errors={len(errors)}")
        
        return {
            "success": success,
            "errors": errors
        }

    except Exception as e:
        logger.error(f"Error removing agent links: {e}")
        return {
            "success": False,
            "mongodb_deleted": 0,
            "qdrant_result": {
                "knowledge_base_deleted": 0,
                "web_catalog_deleted": 0
            },
            "errors": [str(e)]
        }

async def remove_agent_files(agent_id: str, files: list[str]) -> dict:
    """
    Remove specific files from an agent's knowledge base (MongoDB and Qdrant).
    
    Args:
        agent_id: The ID of the agent
        files: List of file names to remove
    
    Returns:
        dict: Result with success status, counts, and errors
    """
    try:
        mongodb_deleted = 0
        qdrant_deleted = 0
        errors = []
        
        # Remove from MongoDB atlas_agent_files collection
        try:
            files_collection = get_collection("atlas_agent_files")
            mongo_result = await files_collection.delete_many({
                "agent_id": agent_id,
                "file_name": {"$in": files}
            })
            mongodb_deleted = mongo_result.deleted_count
            logger.info(f"Deleted {mongodb_deleted} files from MongoDB for agent_id {agent_id}")
        except Exception as e:
            error_msg = f"MongoDB deletion error: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
        
        # Remove from Qdrant agent_knowledge_base collection
        qdrant_filters = {
            "must": [
                {"key": "agent_id", "match": {"value": agent_id}},
                {"key": "knowledge_source", "match": {"any": files}}
            ]
        }
        
        try:
            qdrant_result = await delete_qdrant_points_by_filter(
                collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                filters=qdrant_filters
            )
            if qdrant_result.get("success"):
                # Extract deletion count if available in result
                qdrant_count = qdrant_result.get("result", {}).get("deleted", 0) if isinstance(qdrant_result.get("result"), dict) else 0
                qdrant_deleted = qdrant_count
                logger.info(f"Deleted {qdrant_count} points from {AGENT_KNOWLEDGE_BASE_COLLECTION_NAME} for agent_id {agent_id}")
            else:
                errors.append(f"Qdrant deletion: {qdrant_result.get('message')}")
        except Exception as e:
            error_msg = f"Qdrant deletion error: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
        
        success = (mongodb_deleted > 0 or qdrant_deleted > 0) and len(errors) == 0
        
        logger.info(f"Removed {len(files)} files for agent_id {agent_id}: MongoDB={mongodb_deleted}, Qdrant={qdrant_deleted}, Errors={len(errors)}")
        
        return {
            "success": success,
            "errors": errors
        }

    except Exception as e:
        logger.error(f"Error removing agent files: {e}")
        return {
            "success": False,
            "errors": [str(e)]
        }