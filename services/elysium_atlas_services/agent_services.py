
from typing import Dict, Any, Optional
from logging_config import get_logger
from services.elysium_atlas_services.atlas_url_index_services import index_agent_urls
from services.elysium_atlas_services.atlas_qdrant_services import remove_all_qdrant_agent_points
from services.mongo_services import get_collection
from datetime import datetime, timezone
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA, USER_SETTABLE_AGENT_STATUSES
from config.retrieval_strategy_config import DEFAULT_RETRIEVAL_STRATEGY
from config.lead_collection_config import (
    get_default_lead_collection_config,
    merge_lead_collection_config,
)
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

AGENT_UPDATE_REINDEX_FIELDS = (
    "links",
    "files",
    "custom_texts",
    "qa_pairs",
    "base_url",
    "agent_name",
    "system_prompt",
    "llm_model",
    "temperature",
)


def validate_user_agent_status(request_data: Dict[str, Any]) -> str | None:
    """Validate and normalize agent_status when present on an update request."""
    if "agent_status" not in request_data:
        return None

    agent_status = request_data.get("agent_status")
    if not isinstance(agent_status, str) or not agent_status.strip():
        return "agent_status must be a non-empty string."

    normalized = agent_status.strip().lower()
    if normalized not in USER_SETTABLE_AGENT_STATUSES:
        allowed = ", ".join(sorted(USER_SETTABLE_AGENT_STATUSES))
        return f"agent_status must be one of: {allowed}."

    request_data["agent_status"] = normalized
    return None


def requires_agent_reindex(request_data: Dict[str, Any]) -> bool:
    """Return True when the update payload includes fields that trigger re-indexing."""
    for field in AGENT_UPDATE_REINDEX_FIELDS:
        value = request_data.get(field)
        if value is None:
            continue
        if field in ("links", "files", "custom_texts", "qa_pairs"):
            if isinstance(value, list) and len(value) == 0:
                continue
        return True
    return False


def resolve_post_update_agent_status(request_data: Dict[str, Any]) -> str:
    """
    Determine the agent_status to apply after a re-index update completes.

    Priority:
    1. Explicit agent_status in the update request
    2. Pre-update user-settable status (e.g. disabled before indexing started)
    3. active
    """
    requested_status = request_data.get("agent_status")
    if requested_status in USER_SETTABLE_AGENT_STATUSES:
        return requested_status

    pre_update_status = request_data.get("_pre_update_agent_status")
    if isinstance(pre_update_status, str):
        pre_update_status = pre_update_status.strip().lower()
    if pre_update_status in USER_SETTABLE_AGENT_STATUSES:
        return pre_update_status

    return "active"


async def capture_pre_update_agent_status(agent_id: str, request_data: Dict[str, Any]) -> None:
    """Store the agent's current status so it can be restored after re-indexing."""
    agent = await get_agent_by_id(agent_id)
    pre_update_status = (agent or {}).get("agent_status")
    if isinstance(pre_update_status, str):
        pre_update_status = pre_update_status.strip().lower()
    request_data["_pre_update_agent_status"] = pre_update_status


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

        if "retrieval_strategy" not in document:
            document["retrieval_strategy"] = DEFAULT_RETRIEVAL_STRATEGY

        if "lead_collection_config" not in document:
            document["lead_collection_config"] = get_default_lead_collection_config()

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

async def list_agents_for_team(team_id: str) -> list[dict]:
    """
    List all agents for a given team_id, including their basic data and progress.

    Args:
        team_id: The ID of the team whose agents are to be listed.

    Returns:
        list[dict]: A list of dictionaries containing agent details.
    """
    try:
        collection = get_collection("atlas_agents")

        agent_task_progress = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_task_progress", {})

        agents_cursor = collection.find({"team_id": team_id}).sort("updated_at", -1)

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

        logger.info(f"Listed {len(agents)} agents for team_id: {team_id}")
        return agents

    except Exception as e:
        logger.error(f"Error listing agents for team_id {team_id}: {e}")
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

DEFAULT_DATASOURCE_PAGE_SIZE = 10
MAX_DATASOURCE_PAGE_SIZE = 100


def _normalize_datasource_pagination(page: int, limit: int) -> tuple[int, int]:
    return max(1, page), max(1, min(limit, MAX_DATASOURCE_PAGE_SIZE))


def _build_datasource_pagination_meta(total: int, page: int, limit: int) -> Dict[str, Any]:
    if total == 0:
        return {
            "total": 0,
            "page": 1,
            "limit": limit,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
        }

    total_pages = (total + limit - 1) // limit
    page = min(page, total_pages)
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


def _empty_datasource_page(limit: int = DEFAULT_DATASOURCE_PAGE_SIZE) -> Dict[str, Any]:
    _, normalized_limit = _normalize_datasource_pagination(1, limit)
    return {
        "data": [],
        "total": 0,
        "page": 1,
        "limit": normalized_limit,
        "total_pages": 0,
        "has_next": False,
        "has_prev": False,
    }


def _serialize_agent_datasource_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    serialized = dict(doc)
    serialized.pop("_id", None)

    if "created_at" in serialized and serialized["created_at"] and isinstance(serialized["created_at"], datetime):
        serialized["created_at"] = serialized["created_at"].isoformat()
    if "updated_at" in serialized and serialized["updated_at"] and isinstance(serialized["updated_at"], datetime):
        serialized["updated_at"] = serialized["updated_at"].isoformat()

    return serialized


async def _fetch_paginated_agent_datasource(
    collection_name: str,
    agent_id: str,
    page: int = 1,
    limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
) -> Dict[str, Any]:
    page, limit = _normalize_datasource_pagination(page, limit)
    collection = get_collection(collection_name)
    query: Dict[str, Any] = {"agent_id": agent_id}

    total = await collection.count_documents(query)
    meta = _build_datasource_pagination_meta(total, page, limit)
    page = meta["page"]

    if total == 0:
        return {"data": [], **meta}

    skip = (page - 1) * limit
    cursor = (
        collection.find(query)
        .sort([("updated_at", -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
    )

    items = [_serialize_agent_datasource_doc(doc) async for doc in cursor]
    logger.info(
        f"Fetched {len(items)} items from {collection_name} for agent_id {agent_id} "
        f"(page {page}, limit {limit}, total {total})"
    )
    return {"data": items, **meta}


async def fetch_agent_urls(
    agent_id: str,
    page: int = 1,
    limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
) -> Dict[str, Any]:
    """Fetch indexed URLs for an agent with page-based pagination."""
    try:
        return await _fetch_paginated_agent_datasource("atlas_agent_urls", agent_id, page, limit)
    except Exception as e:
        logger.error(f"Error fetching URLs for agent_id {agent_id}: {e}")
        return _empty_datasource_page(limit)


async def fetch_agent_files(
    agent_id: str,
    page: int = 1,
    limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
) -> Dict[str, Any]:
    """Fetch uploaded files for an agent with page-based pagination."""
    try:
        return await _fetch_paginated_agent_datasource("atlas_agent_files", agent_id, page, limit)
    except Exception as e:
        logger.error(f"Error fetching files for agent_id {agent_id}: {e}")
        return _empty_datasource_page(limit)


async def fetch_agent_custom_texts(
    agent_id: str,
    page: int = 1,
    limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
) -> Dict[str, Any]:
    """Fetch custom texts for an agent with page-based pagination."""
    try:
        return await _fetch_paginated_agent_datasource("atlas_custom_texts", agent_id, page, limit)
    except Exception as e:
        logger.error(f"Error fetching custom texts for agent_id {agent_id}: {e}")
        return _empty_datasource_page(limit)


async def fetch_agent_qa_pairs(
    agent_id: str,
    page: int = 1,
    limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
) -> Dict[str, Any]:
    """Fetch QA pairs for an agent with page-based pagination."""
    try:
        return await _fetch_paginated_agent_datasource("atlas_qa_pairs", agent_id, page, limit)
    except Exception as e:
        logger.error(f"Error fetching QA pairs for agent_id {agent_id}: {e}")
        return _empty_datasource_page(limit)

async def fetch_agent_details_by_id(
    agent_id: str,
    urls_page: int = 1,
    urls_limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
    files_page: int = 1,
    files_limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
    custom_texts_page: int = 1,
    custom_texts_limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
    qa_pairs_page: int = 1,
    qa_pairs_limit: int = DEFAULT_DATASOURCE_PAGE_SIZE,
) -> Optional[Dict[str, Any]]:
    """
    Fetch complete agent details including the first page of related datasource lists.
    """
    try:
        agent_task_progress = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_task_progress", {})

        document = await fetch_agent_document(agent_id)
        if not document:
            return None
        
        agent_current_task = document.get("agent_current_task", "initializing")
        task_progress = agent_task_progress.get(agent_current_task, 0)

        urls_result, files_result, custom_texts_result, qa_pairs_result = await asyncio.gather(
            fetch_agent_urls(agent_id, page=urls_page, limit=urls_limit),
            fetch_agent_files(agent_id, page=files_page, limit=files_limit),
            fetch_agent_custom_texts(agent_id, page=custom_texts_page, limit=custom_texts_limit),
            fetch_agent_qa_pairs(agent_id, page=qa_pairs_page, limit=qa_pairs_limit),
        )
        
        document["progress"] = task_progress
        document["links"] = urls_result
        document["files"] = files_result
        document["custom_texts"] = custom_texts_result
        document["qa_pairs"] = qa_pairs_result
        
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

        final_status = resolve_post_update_agent_status(requestData)
        await update_agent_status(agent_id, final_status)
        
        logger.info(
            f"Successfully updated agent with ID: {agent_id}; "
            f"restored agent_status to '{final_status}'"
        )
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

async def normalize_lead_collection_config_for_update(
    agent_id: str,
    request_data: Dict[str, Any],
) -> str | None:
    """
    If lead_collection_config is present, validate partial fields and merge into request_data.

    Returns:
        Error message when invalid, otherwise None.
    """
    if "lead_collection_config" not in request_data:
        return None

    agent = await get_agent_by_id(agent_id)
    existing = agent.get("lead_collection_config") if agent else None
    merged, error_message = merge_lead_collection_config(
        existing,
        request_data["lead_collection_config"],
    )
    if error_message:
        return error_message

    request_data["lead_collection_config"] = merged
    return None


async def update_agent_basic_attributes(agent_id: str, requestData: Dict[str, Any]) -> bool:
    """
    Update basic agent attributes like icon, color, text color, etc., if present in requestData.
    
    Args:
        agent_id: The ID of the agent
        requestData: The request data containing potential attributes
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # List of basic attributes to update
        basic_attributes = [
            "agent_icon",
            "primary_color",
            "text_color",
            "secondary_color",
            "welcome_message",
            "placeholder_text",
            "retrieval_strategy",
            "lead_collection_config",
        ]
        
        updates = {}
        for attr in basic_attributes:
            if attr in requestData:
                updates[attr] = requestData[attr]
        
        if updates:
            await update_agent_fields(agent_id, updates)
        
        return True
    except Exception as e:
        logger.error(f"Error updating agent attributes for agent_id {agent_id}: {e}")
        return False

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