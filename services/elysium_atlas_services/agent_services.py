
from typing import Dict, Any, Optional
from logging_config import get_logger
from services.mongo_services import get_collection
from datetime import datetime, timezone
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA, USER_SETTABLE_AGENT_STATUSES, DEPRECATED_AGENT_STORED_FIELDS
from config.retrieval_strategy_config import DEFAULT_RETRIEVAL_STRATEGY
from config.human_handover_config import (
    get_default_human_handover_config,
    merge_human_handover_config,
)
from config.lead_collection_config import (
    get_default_lead_collection_config,
    merge_lead_collection_config,
)
from bson import ObjectId
from services.elysium_atlas_services.agent_db_operations import update_agent_status, update_agent_fields, update_agent_current_task, get_agent_by_id, get_agent_fields_by_id
import asyncio
from config.settings import settings

logger = get_logger()

AGENT_UPDATE_REINDEX_FIELDS: tuple[str, ...] = (
    "agent_name",
    "system_prompt",
    "llm_model",
    "temperature",
)


def strip_deprecated_agent_request_fields(request_data: dict[str, Any]) -> None:
    """Drop legacy agent fields from API payloads (ignored, never persisted)."""
    for field in DEPRECATED_AGENT_STORED_FIELDS:
        request_data.pop(field, None)


async def unset_deprecated_agent_stored_fields(agent_id: str) -> None:
    """Remove legacy fields from the atlas_agents document if present."""
    if not DEPRECATED_AGENT_STORED_FIELDS:
        return
    collection = get_collection("atlas_agents")
    await collection.update_one(
        {"_id": ObjectId(agent_id)},
        {"$unset": {field: "" for field in DEPRECATED_AGENT_STORED_FIELDS}},
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
            continue
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


async def normalize_agent_tool_ids_in_request(
    request_data: Dict[str, Any],
    team_id: str,
) -> str | None:
    """Validate tool_ids when present on an agent request. Mutates request_data in place."""
    if "tool_ids" not in request_data:
        return None

    from services.elysium_atlas_services.atlas_tool_services import validate_agent_tool_ids

    normalized, error = await validate_agent_tool_ids(team_id, request_data["tool_ids"])
    if error:
        return error
    request_data["tool_ids"] = normalized
    return None


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
            initial_data = dict(initial_data)
            strip_deprecated_agent_request_fields(initial_data)
            document.update(initial_data)
        
        document["created_at"] = current_time
        document["updated_at"] = current_time

        document["agent_status"] = "active"
        document["agent_current_task"] = "running"

        if "retrieval_strategy" not in document:
            document["retrieval_strategy"] = DEFAULT_RETRIEVAL_STRATEGY

        if "lead_collection_config" not in document:
            document["lead_collection_config"] = get_default_lead_collection_config()

        if "human_handover_config" not in document:
            document["human_handover_config"] = get_default_human_handover_config()

        if "tool_ids" not in document:
            document["tool_ids"] = []

        result = await collection.insert_one(document)
        agent_id = str(result.inserted_id)

        await generate_agent_widget_script(agent_id)
        
        logger.info(f"Created agent document with _id: {agent_id}")
        return agent_id
        
    except Exception as e:
        logger.error(f"Error creating agent document: {e}")
        return None

async def initialize_agent_build_update(requestData: Dict[str, Any]) -> bool:
    """Apply agent configuration on build (knowledge items use /kb-items APIs)."""
    try:
        agent_id = requestData.get("agent_id")
        if not agent_id:
            agent_id = await create_agent_document()
            if not agent_id:
                logger.error("Failed to create agent document")
                return False
            requestData["agent_id"] = agent_id

        updates: dict[str, Any] = {}

        for field in (
            "agent_name",
            "system_prompt",
            "welcome_message",
            "llm_model",
            "temperature",
            "retrieval_strategy",
            "lead_collection_config",
            "human_handover_config",
        ):
            if field in requestData and requestData[field] is not None:
                updates[field] = requestData[field]

        if "tool_ids" in requestData:
            updates["tool_ids"] = requestData["tool_ids"]

        if updates:
            await update_agent_fields(agent_id, updates)

        await unset_deprecated_agent_stored_fields(agent_id)
        await update_agent_current_task(agent_id, "running")
        await update_agent_status(agent_id, "active")
        await generate_agent_widget_script(agent_id)
        return True
    except Exception as e:
        logger.error(f"Error in initialize_agent_build_update: {e}")
        return False

def _serialize_agent_list_item(agent: dict, agent_task_progress: dict) -> dict:
    agent_id = str(agent.get("_id"))
    agent_current_task = agent.get("agent_current_task", "initializing")
    created_at = agent.get("created_at")
    updated_at = agent.get("updated_at")

    return {
        "agent_id": agent_id,
        "agent_name": agent.get("agent_name", "Unknown"),
        "agent_icon": agent.get("agent_icon"),
        "agent_status": agent.get("agent_status", "inactive"),
        "agent_current_task": agent_current_task,
        "progress": agent_task_progress.get(agent_current_task),
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


MAX_AGENT_LIST_PAGE_SIZE = 100


def _normalize_list_pagination(page: int, limit: int) -> tuple[int, int]:
    return max(1, page), max(1, min(limit, MAX_AGENT_LIST_PAGE_SIZE))


def _build_list_pagination_meta(total: int, page: int, limit: int) -> Dict[str, Any]:
    if total == 0:
        return {"total": 0, "page": 1, "limit": limit, "total_pages": 0, "has_next": False, "has_prev": False}
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


async def list_agents_for_team(
    team_id: str,
    page: int = 1,
    limit: int = 10,
) -> dict[str, Any]:
    """
    List paginated agents for a given team_id, including basic data and progress.

    Args:
        team_id: The ID of the team whose agents are to be listed.
        page: 1-based page number.
        limit: Items per page (max 100).

    Returns:
        dict: Agents for the requested page plus pagination metadata.
    """
    page, limit = _normalize_list_pagination(page, limit)
    empty_result = {"agents": [], **_build_list_pagination_meta(0, page, limit)}

    try:
        collection = get_collection("atlas_agents")
        agent_task_progress = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_task_progress", {})
        query = {"team_id": team_id}

        total = await collection.count_documents(query)
        meta = _build_list_pagination_meta(total, page, limit)
        page = meta["page"]

        if total == 0:
            return empty_result

        skip = (page - 1) * limit
        cursor = (
            collection.find(query)
            .sort([("updated_at", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
        )

        agents = [
            _serialize_agent_list_item(agent, agent_task_progress)
            async for agent in cursor
        ]

        logger.info(
            f"Listed {len(agents)} agents for team_id: {team_id} "
            f"(page {page}, limit {limit}, total {total})"
        )
        return {"agents": agents, **meta}

    except Exception as e:
        logger.error(f"Error listing agents for team_id {team_id}: {e}")
        return empty_result

async def remove_agent_by_id(agent_id: str) -> bool:
    """Remove agent document and KB attachment rows. Team KB items are not deleted."""
    try:
        from services.elysium_atlas_services.kb_item.kb_attachment_service import delete_attachments_for_agent

        await delete_attachments_for_agent(agent_id)
        collection = get_collection("atlas_agents")
        agent_result = await collection.delete_one({"_id": ObjectId(agent_id)})
        return agent_result.deleted_count > 0
    except Exception as e:
        logger.error(f"Error removing agent with ID {agent_id}: {e}")
        return False

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

            if "tool_ids" not in document:
                document["tool_ids"] = []

            deprecated_present = any(field in document for field in DEPRECATED_AGENT_STORED_FIELDS)
            for field in DEPRECATED_AGENT_STORED_FIELDS:
                document.pop(field, None)

            if deprecated_present:
                await unset_deprecated_agent_stored_fields(agent_id)

            return document
        else:
            logger.warning(f"No agent found with ID: {agent_id}")
            return None
    except Exception as e:
        logger.error(f"Error fetching agent document for agent_id {agent_id}: {e}")
        return None

async def fetch_agent_details_by_id(agent_id: str) -> Optional[Dict[str, Any]]:
    """Fetch agent document, KB attachments, and task progress."""
    try:
        from services.elysium_atlas_services.kb_item.kb_attachment_service import list_kb_attachments_for_agent

        agent_task_progress = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_task_progress", {})
        document = await fetch_agent_document(agent_id)
        if not document:
            return None
        agent_current_task = document.get("agent_current_task", "initializing")
        document["progress"] = agent_task_progress.get(agent_current_task, 0)
        document["kb_attachments"] = await list_kb_attachments_for_agent(agent_id)
        return document
    except Exception as e:
        logger.error(f"Error fetching agent details for agent_id {agent_id}: {e}")
        return None


async def initialize_agent_update(requestData: Dict[str, Any]) -> bool:
    """Update agent metadata only (no knowledge indexing)."""
    try:
        agent_id = requestData.get("agent_id")
        if not agent_id:
            logger.error("agent_id is required for update operation")
            return False

        await update_agent_current_task(agent_id, "updating agent metadata")
        updates: dict[str, Any] = {}

        for field in (
            "agent_name",
            "system_prompt",
            "welcome_message",
            "llm_model",
            "temperature",
        ):
            val = requestData.get(field)
            if val is not None:
                updates[field] = val

        if isinstance(requestData.get("temperature"), (int, float)):
            updates["temperature"] = requestData["temperature"]

        if "tool_ids" in requestData:
            updates["tool_ids"] = requestData["tool_ids"]

        if updates:
            await update_agent_fields(agent_id, updates)

        await unset_deprecated_agent_stored_fields(agent_id)
        await update_agent_current_task(agent_id, "running")
        final_status = resolve_post_update_agent_status(requestData)
        await update_agent_status(agent_id, final_status)
        return True
    except Exception as e:
        logger.error(f"Error updating agent: {e}")
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


async def normalize_human_handover_config_for_update(
    agent_id: str,
    request_data: Dict[str, Any],
) -> str | None:
    """
    If human_handover_config is present, validate partial fields and merge into request_data.

    Returns:
        Error message when invalid, otherwise None.
    """
    if "human_handover_config" not in request_data:
        return None

    agent = await get_agent_by_id(agent_id)
    existing = agent.get("human_handover_config") if agent else None
    merged, error_message = merge_human_handover_config(
        existing,
        request_data["human_handover_config"],
    )
    if error_message:
        return error_message

    request_data["human_handover_config"] = merged
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
            "human_handover_config",
            "tool_ids",
        ]
        
        updates = {}
        for attr in basic_attributes:
            if attr in requestData:
                updates[attr] = requestData[attr]
        
        if updates:
            await update_agent_fields(agent_id, updates)

        await unset_deprecated_agent_stored_fields(agent_id)
        return True
    except Exception as e:
        logger.error(f"Error updating agent attributes for agent_id {agent_id}: {e}")
        return False