from typing import Dict, Any, List
from logging_config import get_logger
from services.mongo_services import get_collection
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from config.atlas_chat_config import clamp_chat_session_list_page_size, validate_chat_session_search_query
import datetime
from bson import ObjectId
import random
import asyncio
import uuid
import re

logger = get_logger()


def coerce_utc_datetime(value) -> datetime.datetime:
    """
    Normalize a timestamp to timezone-aware UTC datetime for MongoDB storage.
    Accepts datetime, ISO strings (including trailing Z), or None (uses now).
    """
    if value is None:
        return datetime.datetime.now(datetime.timezone.utc)

    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc)

    if isinstance(value, str):
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(normalized).astimezone(datetime.timezone.utc)

    return datetime.datetime.now(datetime.timezone.utc)


def format_utc_datetime_for_client(value: datetime.datetime) -> str:
    """ISO-8601 string for sockets/API payloads."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    else:
        value = value.astimezone(datetime.timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def serialize_chat_session_document_for_api(document: Dict[str, Any]) -> Dict[str, Any]:
    """Convert atlas_chat_sessions Mongo fields to JSON-safe values."""
    serialized = dict(document)
    mongo_id = serialized.get("_id")
    if mongo_id is not None:
        serialized["_id"] = str(mongo_id)
    for key, value in list(serialized.items()):
        if isinstance(value, datetime.datetime):
            serialized[key] = format_utc_datetime_for_client(value)

    lead_collection = serialized.get("lead_collection")
    if isinstance(lead_collection, dict):
        lead_copy = dict(lead_collection)
        completed_at = lead_copy.get("completed_at")
        if isinstance(completed_at, datetime.datetime):
            lead_copy["completed_at"] = format_utc_datetime_for_client(completed_at)
        serialized["lead_collection"] = lead_copy

    handover = serialized.get("handover")
    if isinstance(handover, dict):
        handover_copy = dict(handover)
        requested_at = handover_copy.get("requested_at")
        if isinstance(requested_at, datetime.datetime):
            handover_copy["requested_at"] = format_utc_datetime_for_client(requested_at)
        serialized["handover"] = handover_copy

    return serialized


def serialize_chat_message_for_client(message: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Normalize a chat message document for API/socket responses."""
    if not message:
        return None

    serialized = dict(message)
    created_at = serialized.get("created_at")
    if isinstance(created_at, datetime.datetime):
        serialized["created_at"] = format_utc_datetime_for_client(created_at)
    read_at = serialized.get("read_at")
    if isinstance(read_at, datetime.datetime):
        serialized["read_at"] = format_utc_datetime_for_client(read_at)
    read_by = serialized.get("read_by")
    if read_by is not None:
        serialized["read_by"] = str(read_by)
    mongo_id = serialized.get("_id")
    if mongo_id is not None:
        serialized["_id"] = str(mongo_id)
    return serialized


def build_chat_message_document_from_payload(
    payload: Dict[str, Any] | None,
    chat_session_id: str,
    agent_id: str,
    conversation_id: str | None = None,
) -> Dict[str, Any] | None:
    """
    Build a single atlas_chat_mesages document with UTC datetime created_at.
    """
    if not payload or not isinstance(payload, dict):
        if payload is not None:
            logger.warning("Invalid payload type for chat message; expected dict")
        return None

    role = payload.get("role")
    content = payload.get("content")
    if not role or content is None:
        logger.warning("Missing role or content in chat message payload")
        return None

    doc: Dict[str, Any] = {
        "chat_session_id": chat_session_id,
        "agent_id": agent_id,
        "message_id": payload.get("message_id"),
        "role": role,
        "content": content,
        "created_at": coerce_utc_datetime(payload.get("created_at")),
    }

    if conversation_id is not None:
        doc["conversation_id"] = conversation_id

    team_member_id = payload.get("team_member_id")
    if team_member_id is not None:
        doc["team_member_id"] = team_member_id

    return doc


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
        limit = requestData.get("limit", 50)

        if not chat_session_id:
            logger.warning("chat_session_id missing in requestData")
            return None

        collection = get_collection("atlas_chat_sessions")

        # Try to find existing document by chat_session_id and agent_id
        document = await collection.find_one({"chat_session_id": chat_session_id, "agent_id": agent_id})
        if document:
            document = serialize_chat_session_document_for_api(document)

            # Ensure conversation_id exists; backfill if missing from older documents
            if not document.get("conversation_id"):
                new_conversation_id = str(uuid.uuid4())
                document["conversation_id"] = new_conversation_id
                async def _backfill_conversation_id(cid=new_conversation_id, doc_id=document["_id"]):
                    await collection.update_one(
                        {"_id": ObjectId(doc_id)},
                        {"$set": {"conversation_id": cid}}
                    )
                asyncio.create_task(_backfill_conversation_id())
            
            # Update visitor_at if provided
            visitor_at = requestData.get("visitor_at")
            if visitor_at is not None:
                document["visitor_at"] = visitor_at
                # Update in DB asynchronously
                async def update_visitor():
                    await collection.update_one(
                        {"_id": ObjectId(document["_id"])},
                        {"$set": {"visitor_at": visitor_at}}
                    )
                asyncio.create_task(update_visitor())

            # Update source if provided and truthy
            source = requestData.get("source")
            if source:
                document["source"] = source
                # Update in DB asynchronously
                async def update_source(src=source, doc_id=document["_id"]):
                    await collection.update_one(
                        {"_id": ObjectId(doc_id)},
                        {"$set": {"source": src}}
                    )
                asyncio.create_task(update_source())
            
            # Retrieve messages for the session, scoped to the current conversation
            messages = await get_chat_messages_for_session(
                agent_id,
                chat_session_id,
                limit=limit,
                conversation_id=document.get("conversation_id"),
            )
            document["messages"] = messages
            document = await enrich_chat_session_with_handler_name(document)

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
                "conversation_id": str(uuid.uuid4()),
                "created_at": datetime.datetime.now(datetime.timezone.utc),
                "last_message_at": datetime.datetime.now(datetime.timezone.utc),
                "last_connected_at": None,
            }
            visitor_at = requestData.get("visitor_at")
            if visitor_at:
                update_dict["visitor_at"] = visitor_at
            source = requestData.get("source")
            if source:
                update_dict["source"] = source
            document.update(update_dict)
            
            result = await collection.insert_one(document)
            document["_id"] = str(result.inserted_id)
            document = serialize_chat_session_document_for_api(document)
            
            # For new session, messages will be empty
            document["messages"] = []
            document = await enrich_chat_session_with_handler_name(document)

            logger.info(f"Created new chat session document with chat_session_id: {chat_session_id} and agent_id: {agent_id}")
            return document

    except Exception as e:
        logger.error(f"Error in get_chat_session_data: {str(e)}")
        return None

async def get_chat_messages_for_session(
    agent_id: str,
    chat_session_id: str,
    limit: int = 50,
    conversation_id: str | None = None,
) -> list[Dict[str, Any]]:
    """
    Retrieve chat messages for a specific session, sorted by created_at ascending.
    When conversation_id is provided, only messages belonging to that conversation
    thread are returned.

    Args:
        agent_id: The agent identifier.
        chat_session_id: The chat session identifier.
        limit: Maximum number of messages to retrieve.
        conversation_id: Optional conversation thread identifier to filter by.

    Returns:
        List of message documents with message_id, role, content, created_at.
    """
    try:
        if not agent_id or not chat_session_id:
            logger.warning("agent_id and chat_session_id are required")
            return []

        collection = get_collection("atlas_chat_mesages")

        query: Dict[str, Any] = {"agent_id": agent_id, "chat_session_id": chat_session_id}
        if conversation_id:
            query["conversation_id"] = conversation_id

        # Find the latest `limit` messages by sorting descending in Mongo,
        # then reverse in Python so the caller still receives messages
        # in chronological order (oldest -> newest, newest at the end).
        cursor = collection.find(
            query,
            {
                "message_id": 1,
                "role": 1,
                "content": 1,
                "created_at": 1,
                "read_at": 1,
                "read_by": 1,
                "conversation_id": 1,
                "_id": 1,
            },
        ).sort("created_at", -1).limit(limit)

        messages = await cursor.to_list(length=None)
        messages.reverse()

        messages = [serialize_chat_message_for_client(msg) for msg in messages]

        logger.info(
            "Retrieved %d messages for chat_session_id=%s agent_id=%s conversation_id=%s",
            len(messages),
            chat_session_id,
            agent_id,
            conversation_id,
        )

        return messages

    except Exception as e:
        logger.error(f"Error retrieving chat messages: {str(e)}")
        return []


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


CHAT_SESSION_VISITOR_LIST_FIELDS = (
    "chat_session_id",
    "created_at",
    "last_message_at",
    "last_connected_at",
    "first_message_at",
    "alias_name",
    "geo_data",
    "visitor_at",
    "visitor_online",
    "in_conversation_with",
    "status",
    "resolved_at",
    "resolved_by",
    "lead_collection",
    "handover",
)


def _format_user_full_name(first_name: str | None, last_name: str | None) -> str | None:
    parts = [str(part).strip() for part in (first_name, last_name) if part and str(part).strip()]
    return " ".join(parts) if parts else None


async def get_user_full_names_by_ids(user_ids: list[str]) -> dict[str, str | None]:
    """Batch-resolve display names from elysium_atlas_users (first + last name)."""
    from bson.errors import InvalidId

    unique_ids = list({uid for uid in user_ids if uid})
    if not unique_ids:
        return {}

    object_ids: list[ObjectId] = []
    for uid in unique_ids:
        try:
            object_ids.append(ObjectId(uid))
        except InvalidId:
            logger.warning(f"Skipping invalid user_id for name lookup: {uid}")

    if not object_ids:
        return {}

    collection = get_collection("elysium_atlas_users")
    cursor = collection.find(
        {"_id": {"$in": object_ids}},
        {"first_name": 1, "last_name": 1},
    )
    docs = await cursor.to_list(length=len(object_ids))

    names: dict[str, str | None] = {}
    for doc in docs:
        uid = str(doc["_id"])
        names[uid] = _format_user_full_name(doc.get("first_name"), doc.get("last_name"))
    return names


async def enrich_visitor_list_rows_with_handler_names(rows: list[dict]) -> list[dict]:
    """Add in_conversation_with_name to agent_visitors_list / search rows."""
    handler_ids = [
        row.get("in_conversation_with")
        for row in rows
        if row.get("in_conversation_with")
    ]
    names_by_id = await get_user_full_names_by_ids(handler_ids)
    for row in rows:
        handler_id = row.get("in_conversation_with")
        row["in_conversation_with_name"] = names_by_id.get(handler_id) if handler_id else None
    return rows


async def enrich_chat_session_with_handler_name(document: Dict[str, Any]) -> Dict[str, Any]:
    """Add in_conversation_with_name for visitor widget restore (e.g. get-agent-fields)."""
    handler_id = document.get("in_conversation_with")
    if not handler_id:
        document["in_conversation_with_name"] = None
        return document

    names_by_id = await get_user_full_names_by_ids([str(handler_id)])
    document["in_conversation_with_name"] = names_by_id.get(str(handler_id))
    return document


async def ensure_chat_session_for_visitor(
    agent_id: str,
    chat_session_id: str,
    *,
    visitor_at: str | None = None,
    source: str | None = None,
) -> bool:
    """
    Create an atlas_chat_sessions document when a visitor connects, if one does not exist.

    Ensures chat sessions appear in the agent visitors list before the first message.

    Returns:
        True if a new session document was inserted, False if it already existed.
    """
    try:
        if not agent_id or not chat_session_id:
            return False

        collection = get_collection("atlas_chat_sessions")
        existing = await collection.find_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"_id": 1},
        )
        if existing:
            return False

        init_config = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("chat_session_init_config", {})
        document = init_config.copy()
        document["chat_session_id"] = chat_session_id
        document["agent_id"] = agent_id

        agent_display_name = await get_agent_alias_name(agent_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        document.update(
            {
                "agent_name": agent_display_name,
                "channel": get_channel_from_session_id(chat_session_id),
                "conversation_id": str(uuid.uuid4()),
                "created_at": now,
                "last_message_at": None,
            }
        )
        if visitor_at:
            document["visitor_at"] = visitor_at
        if source:
            document["source"] = source

        await collection.insert_one(document)
        logger.info(
            f"Created chat session on visitor connect: chat_session_id={chat_session_id} "
            f"agent_id={agent_id}"
        )

        from services.elysium_atlas_services.atlas_chat_session_audit_services import (
            AUDIT_ACTOR_VISITOR,
            AUDIT_EVENT_VISITOR_FIRST_CONNECTED,
            record_chat_session_audit,
        )

        await record_chat_session_audit(
            agent_id,
            chat_session_id,
            AUDIT_EVENT_VISITOR_FIRST_CONNECTED,
            actor_type=AUDIT_ACTOR_VISITOR,
            occurred_at=now,
            metadata={"channel": document.get("channel")},
        )
        return True

    except Exception as e:
        logger.error(f"Error in ensure_chat_session_for_visitor: {str(e)}")
        return False


async def count_chat_sessions_for_agent(agent_id: str) -> int:
    """Total persisted chat sessions for an agent (MongoDB)."""
    try:
        if not agent_id:
            return 0
        collection = get_collection("atlas_chat_sessions")
        return await collection.count_documents({"agent_id": agent_id})
    except Exception as e:
        logger.error(f"Error counting chat sessions for agent {agent_id}: {str(e)}")
        return 0


async def count_handover_requested_sessions_for_agent(agent_id: str) -> int:
    """Sessions where a visitor requested human handover and no team member has taken over yet."""
    try:
        if not agent_id:
            return 0

        from config.human_handover_constants import HANDOVER_STATUS_REQUESTED

        collection = get_collection("atlas_chat_sessions")
        return await collection.count_documents(
            {
                "agent_id": agent_id,
                "handover.status": HANDOVER_STATUS_REQUESTED,
            }
        )
    except Exception as e:
        logger.error(
            f"Error counting handover-requested sessions for agent {agent_id}: {str(e)}"
        )
        return 0


async def get_agent_chat_sessions_summary(agent_id: str) -> Dict[str, Any] | None:
    """
    Lightweight chat-session counts for dashboard polling.

    Does not return list rows — use socket atlas-agent-visitors-list or search for that.
    """
    import asyncio

    from services.elysium_atlas_services.atlas_presence_services import get_visitor_count_for_agent

    if not agent_id:
        return None

    try:
        total, online_count, handover_requested_count = await asyncio.gather(
            count_chat_sessions_for_agent(agent_id),
            get_visitor_count_for_agent(agent_id),
            count_handover_requested_sessions_for_agent(agent_id),
        )
        return {
            "agent_id": agent_id,
            "total": total,
            "online_count": online_count,
            "handover_requested_count": handover_requested_count,
        }
    except Exception as e:
        logger.error(f"Error fetching chat sessions summary for agent {agent_id}: {str(e)}")
        return None


def format_chat_session_as_visitor_row(
    session_doc: Dict[str, Any],
    agent_id: str,
    live_visitor: Dict[str, Any] | None = None,
    lead_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Shape an atlas_chat_sessions document for agent_visitors_list socket payloads.

    Presence (visitor_online) is read from the session document (Mongo source of truth).
    Socket routing uses per-session Socket.IO rooms — sid is not exposed to clients.
    """
    from config.atlas_chat_config import (
        CHAT_SESSION_STATUS_ACTIVE,
        CHAT_SESSION_STATUS_IN_CONVERSATION,
        CHAT_SESSION_STATUS_RESOLVED,
    )
    from services.elysium_atlas_services.atlas_presence_services import session_doc_to_live_visitor

    if live_visitor is None:
        live_visitor = session_doc_to_live_visitor(session_doc)

    chat_session_id = session_doc.get("chat_session_id")
    is_online = bool(session_doc.get("visitor_online")) and live_visitor is not None

    persisted_status = session_doc.get("status")
    in_conversation_with = session_doc.get("in_conversation_with")
    if persisted_status == CHAT_SESSION_STATUS_RESOLVED:
        status = CHAT_SESSION_STATUS_RESOLVED
        in_conversation_with = None
    elif persisted_status:
        status = persisted_status
    else:
        status = (
            CHAT_SESSION_STATUS_IN_CONVERSATION
            if in_conversation_with
            else CHAT_SESSION_STATUS_ACTIVE
        )

    row: Dict[str, Any] = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "created_at": _serialize_session_datetime(session_doc.get("created_at")),
        "last_message_at": _serialize_session_datetime(session_doc.get("last_message_at")),
        "last_connected_at": _serialize_session_datetime(session_doc.get("last_connected_at")),
        "sid": None,
        "alias_name": session_doc.get("alias_name"),
        "in_conversation_with": in_conversation_with,
        "in_conversation_with_name": None,
        "status": status,
        "geo_data": session_doc.get("geo_data"),
        "visitor_at": session_doc.get("visitor_at"),
        "visitor_online": is_online,
        "first_message_at": _serialize_session_datetime(session_doc.get("first_message_at")),
        "resolved_at": _serialize_session_datetime(session_doc.get("resolved_at")),
        "resolved_by": session_doc.get("resolved_by"),
    }

    from services.elysium_atlas_services.lead_collection_services import (
        build_lead_collection_client_summary,
    )

    session_lead = session_doc.get("lead_collection") if isinstance(session_doc.get("lead_collection"), dict) else None
    lead_summary = build_lead_collection_client_summary(lead_config, session_lead)
    row["lead_collection"] = lead_summary
    row["lead_status"] = lead_summary.get("list_status")
    row["lead_email"] = next(
        (field["value"] for field in lead_summary.get("fields", []) if field.get("key") == "email" and field.get("captured")),
        None,
    )
    row["lead_name"] = next(
        (field["value"] for field in lead_summary.get("fields", []) if field.get("key") == "name" and field.get("captured")),
        None,
    )

    from services.elysium_atlas_services.human_handover_services import (
        build_handover_list_fields,
        get_handover_session_state,
    )

    handover_fields = build_handover_list_fields(get_handover_session_state(session_doc))
    row.update(handover_fields)

    return row


async def _lead_config_for_agent_visitor_list(agent_id: str) -> dict:
    from services.elysium_atlas_services.lead_collection_config_services import (
        get_lead_collection_config_for_agent,
    )

    return (await get_lead_collection_config_for_agent(agent_id)) or {}


async def build_chat_session_broadcast_row(
    agent_id: str,
    chat_session_id: str,
) -> dict | None:
    """Build a single agent_visitors_list-shaped row for real-time dashboard patches."""
    if not agent_id or not chat_session_id:
        return None

    collection = get_collection("atlas_chat_sessions")
    session_doc = await collection.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
    )
    if not session_doc:
        return None

    lead_config = await _lead_config_for_agent_visitor_list(agent_id)
    row = format_chat_session_as_visitor_row(session_doc, agent_id, lead_config=lead_config)
    await enrich_visitor_list_rows_with_handler_names([row])
    return row


async def get_chat_session_alias_names_by_keys(
    session_keys: list[tuple[str, str]],
) -> dict[tuple[str, str], str | None]:
    """
    Batch-fetch alias_name from atlas_chat_sessions for (agent_id, chat_session_id) pairs.

    Missing sessions or unset aliases map to None.
    """
    if not session_keys:
        return {}

    by_agent: dict[str, list[str]] = {}
    for agent_id, chat_session_id in session_keys:
        if not agent_id or not chat_session_id:
            continue
        session_ids = by_agent.setdefault(str(agent_id), [])
        if chat_session_id not in session_ids:
            session_ids.append(chat_session_id)

    if not by_agent:
        return {}

    try:
        collection = get_collection("atlas_chat_sessions")
        or_clauses = [
            {"agent_id": agent_id, "chat_session_id": {"$in": session_ids}}
            for agent_id, session_ids in by_agent.items()
        ]
        cursor = collection.find(
            {"$or": or_clauses},
            {"_id": 0, "agent_id": 1, "chat_session_id": 1, "alias_name": 1},
        )

        aliases: dict[tuple[str, str], str | None] = {}
        async for doc in cursor:
            agent_id = doc.get("agent_id")
            chat_session_id = doc.get("chat_session_id")
            if not agent_id or not chat_session_id:
                continue
            key = (str(agent_id), str(chat_session_id))
            alias_name = doc.get("alias_name")
            if isinstance(alias_name, str) and alias_name.strip():
                aliases[key] = alias_name.strip()
            else:
                aliases[key] = None
        return aliases
    except Exception as e:
        logger.error("Error batch-fetching chat session alias names: %s", e, exc_info=True)
        return {}


async def get_chat_sessions_by_ids_for_agent(
    agent_id: str,
    chat_session_ids: list[str],
) -> list[Dict[str, Any]] | None:
    """
    Fetch fresh list rows for specific chat sessions (visible-page refresh).

    Returns rows in the same shape as agent_visitors_list.visitors.
    Missing or cross-agent ids are omitted.
    """
    try:
        if not agent_id or not chat_session_ids:
            return None

        collection = get_collection("atlas_chat_sessions")
        projection = {field: 1 for field in CHAT_SESSION_VISITOR_LIST_FIELDS}
        projection["_id"] = 0

        cursor = collection.find(
            {
                "agent_id": agent_id,
                "chat_session_id": {"$in": chat_session_ids},
            },
            projection,
        )
        session_docs = await cursor.to_list(length=None)
        doc_by_id = {
            doc.get("chat_session_id"): doc
            for doc in session_docs
            if doc.get("chat_session_id")
        }

        lead_config = await _lead_config_for_agent_visitor_list(agent_id)
        visitors = [
            format_chat_session_as_visitor_row(doc_by_id[session_id], agent_id, lead_config=lead_config)
            for session_id in chat_session_ids
            if session_id in doc_by_id
        ]
        return await enrich_visitor_list_rows_with_handler_names(visitors)

    except Exception as e:
        logger.error(
            f"Error fetching chat sessions by ids for agent {agent_id}: {str(e)}"
        )
        return None


async def get_paginated_chat_sessions_for_agent_list(
    agent_id: str,
    page: int = 1,
    size: int = 100,
) -> dict | None:
    """
    Paginated chat sessions for an agent, sorted by last_message_at descending.

    Out-of-range pages are clamped to the last valid page when sessions exist.
    Online presence is stored on each atlas_chat_sessions document (visitor_online).
    """
    try:
        if not agent_id:
            return None

        page = max(1, page)
        size = max(1, size)

        collection = get_collection("atlas_chat_sessions")
        query = {"agent_id": agent_id}
        total = await collection.count_documents(query)

        if total == 0:
            return {
                "visitors": [],
                "total": 0,
                "page": 1,
                "size": size,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            }

        total_pages = (total + size - 1) // size
        page = min(page, total_pages)
        skip = (page - 1) * size

        projection = {field: 1 for field in CHAT_SESSION_VISITOR_LIST_FIELDS}
        projection["_id"] = 0

        cursor = (
            collection.find(query, projection)
            .sort([("last_message_at", -1), ("last_connected_at", -1), ("created_at", -1)])
            .skip(skip)
            .limit(size)
        )
        session_docs = await cursor.to_list(length=None)

        lead_config = await _lead_config_for_agent_visitor_list(agent_id)
        visitors = [
            format_chat_session_as_visitor_row(doc, agent_id, lead_config=lead_config)
            for doc in session_docs
        ]
        visitors = await enrich_visitor_list_rows_with_handler_names(visitors)

        logger.info(
            f"Retrieved {len(visitors)} chat session(s) for agent {agent_id} "
            f"(page {page}, size {size}, total {total}, total_pages {total_pages})"
        )
        return {
            "visitors": visitors,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

    except Exception as e:
        logger.error(f"Error getting paginated chat sessions for agent {agent_id}: {str(e)}")
        return None


def _build_chat_session_list_page_result(
    visitors: list[Dict[str, Any]],
    *,
    total: int,
    page: int,
    size: int,
) -> dict:
    if total == 0:
        return {
            "visitors": [],
            "total": 0,
            "page": 1,
            "size": size,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
        }

    total_pages = (total + size - 1) // size
    page = min(max(1, page), total_pages)
    return {
        "visitors": visitors,
        "total": total,
        "page": page,
        "size": size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


async def search_paginated_chat_sessions_for_agent(
    agent_id: str,
    query: str,
    page: int = 1,
    size: int = 100,
) -> dict | None:
    """
    Paginated chat session search for an agent.

    Matches case-insensitive substrings on chat_session_id or alias_name.
    Sorted by last_message_at descending (same as the default list).
    """
    try:
        if not agent_id:
            return None

        is_valid, error_message, normalized_query = validate_chat_session_search_query(query)
        if not is_valid:
            return {
                "success": False,
                "message": error_message,
                "query": normalized_query,
                **_build_chat_session_list_page_result([], total=0, page=1, size=clamp_chat_session_list_page_size(size)),
            }

        page = max(1, page)
        size = clamp_chat_session_list_page_size(size)
        pattern = re.escape(normalized_query)

        collection = get_collection("atlas_chat_sessions")
        search_filter: Dict[str, Any] = {
            "agent_id": agent_id,
            "$or": [
                {"chat_session_id": {"$regex": pattern, "$options": "i"}},
                {"alias_name": {"$regex": pattern, "$options": "i"}},
            ],
        }

        total = await collection.count_documents(search_filter)
        if total == 0:
            return {
                "success": True,
                "query": normalized_query,
                **_build_chat_session_list_page_result([], total=0, page=1, size=size),
            }

        total_pages = (total + size - 1) // size
        page = min(page, total_pages)
        skip = (page - 1) * size

        projection = {field: 1 for field in CHAT_SESSION_VISITOR_LIST_FIELDS}
        projection["_id"] = 0

        cursor = (
            collection.find(search_filter, projection)
            .sort([("last_message_at", -1), ("last_connected_at", -1), ("created_at", -1)])
            .skip(skip)
            .limit(size)
        )
        session_docs = await cursor.to_list(length=None)

        lead_config = await _lead_config_for_agent_visitor_list(agent_id)
        visitors = [
            format_chat_session_as_visitor_row(doc, agent_id, lead_config=lead_config)
            for doc in session_docs
        ]
        visitors = await enrich_visitor_list_rows_with_handler_names(visitors)

        logger.info(
            f"Search returned {len(visitors)} chat session(s) for agent {agent_id} "
            f"query={normalized_query!r} (page {page}, size {size}, total {total}, total_pages {total_pages})"
        )
        return {
            "success": True,
            "query": normalized_query,
            **_build_chat_session_list_page_result(visitors, total=total, page=page, size=size),
        }

    except Exception as e:
        logger.error(f"Error searching chat sessions for agent {agent_id}: {str(e)}")
        return None


TEAM_MEMBER_CHAT_SESSION_RESPONSE_FIELDS = (
    "chat_session_id",
    "alias_name",
    "last_message_at",
    "visitor_online",
    "last_connected_at",
    "geo_data",
)


def _build_team_member_chat_sessions_base_query(
    user_id: str,
    agent_id: str | None = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"team_member_ids": user_id}
    if agent_id:
        query["agent_id"] = agent_id
    return query


async def enrich_team_member_chat_session_rows(documents: list[dict]) -> list[dict]:
    """Add last_message and unread counts to team-member chat session API rows."""
    messages_collection = get_collection("atlas_chat_mesages")

    async def _get_last_message(chat_session_id, agent_id, conversation_id):
        if not (chat_session_id and agent_id and conversation_id):
            return None
        msg = await messages_collection.find_one(
            {
                "chat_session_id": chat_session_id,
                "agent_id": agent_id,
                "conversation_id": conversation_id,
            },
            sort=[("created_at", -1)],
        )
        if msg:
            msg.pop("_id", None)
            msg = serialize_chat_message_for_client(msg)
        return msg

    last_messages = await asyncio.gather(*[
        _get_last_message(
            doc.get("chat_session_id"),
            doc.get("agent_id"),
            doc.get("conversation_id"),
        )
        for doc in documents
    ])

    unread_counts = await asyncio.gather(*[
        count_unread_visitor_messages(
            doc.get("agent_id"),
            doc.get("chat_session_id"),
            doc.get("conversation_id"),
        )
        for doc in documents
    ])

    serialised: list[dict] = []
    for doc, last_msg, unread_count in zip(documents, last_messages, unread_counts):
        entry: Dict[str, Any] = {}
        for field in TEAM_MEMBER_CHAT_SESSION_RESPONSE_FIELDS:
            val = doc.get(field)
            if isinstance(val, datetime.datetime):
                val = val.isoformat()
            entry[field] = val
        entry["last_message"] = last_msg
        entry["has_unread_messages"] = unread_count > 0
        entry["unread_visitor_message_count"] = unread_count
        serialised.append(entry)
    return serialised


async def get_paginated_team_member_chat_sessions(
    user_id: str,
    *,
    agent_id: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict | None:
    """Paginated chat sessions where the team member participated (team_member_ids)."""
    try:
        if not user_id:
            return None

        page = max(1, page)
        limit = clamp_chat_session_list_page_size(limit)
        query = _build_team_member_chat_sessions_base_query(user_id, agent_id)

        collection = get_collection("atlas_chat_sessions")
        total = await collection.count_documents(query)
        skip = (page - 1) * limit

        cursor = (
            collection.find(query)
            .sort("last_message_at", -1)
            .skip(skip)
            .limit(limit)
        )
        documents = await cursor.to_list(length=None)
        data = await enrich_team_member_chat_session_rows(documents)

        return {
            "data": data,
            "total": total,
            "page": page,
            "limit": limit,
            "has_next": (skip + limit) < total,
            "has_prev": page > 1,
        }
    except Exception as e:
        logger.error(f"Error fetching team member chat sessions for user_id={user_id}: {str(e)}")
        return None


async def search_paginated_team_member_chat_sessions(
    user_id: str,
    query: str,
    *,
    agent_id: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[dict | None, str | None]:
    """
    Search team-member chat sessions by chat_session_id or alias_name substring.

    Returns:
        (result_dict, validation_error_message)
    """
    try:
        if not user_id:
            return None, "user_id is required."

        is_valid, error_message, normalized_query = validate_chat_session_search_query(query)
        if not is_valid:
            return None, error_message

        page = max(1, page)
        limit = clamp_chat_session_list_page_size(limit)
        pattern = re.escape(normalized_query)

        base_query = _build_team_member_chat_sessions_base_query(user_id, agent_id)
        search_filter: Dict[str, Any] = {
            **base_query,
            "$or": [
                {"chat_session_id": {"$regex": pattern, "$options": "i"}},
                {"alias_name": {"$regex": pattern, "$options": "i"}},
            ],
        }

        collection = get_collection("atlas_chat_sessions")
        total = await collection.count_documents(search_filter)
        skip = (page - 1) * limit

        cursor = (
            collection.find(search_filter)
            .sort("last_message_at", -1)
            .skip(skip)
            .limit(limit)
        )
        documents = await cursor.to_list(length=None)
        data = await enrich_team_member_chat_session_rows(documents)

        logger.info(
            f"Team member search returned {len(data)} session(s) for user_id={user_id} "
            f"query={normalized_query!r} agent_id={agent_id} page={page} limit={limit} total={total}"
        )
        return {
            "query": normalized_query,
            "data": data,
            "total": total,
            "page": page,
            "limit": limit,
            "has_next": (skip + limit) < total,
            "has_prev": page > 1,
        }, None

    except Exception as e:
        logger.error(f"Error searching team member chat sessions for user_id={user_id}: {str(e)}")
        return None, str(e)


def build_chat_message_documents(
    chat_session_id: str,
    agent_id: str,
    user_message_payload: Dict[str, Any] | None = None,
    agent_message_payload: Dict[str, Any] | None = None,
    conversation_id: str | None = None,
) -> list[Dict[str, Any]]:
    """
    Build message documents for the provided payloads.

    Args:
        chat_session_id: The chat session identifier.
        agent_id: The agent identifier.
        user_message_payload: Optional message payload sent by the user.
        agent_message_payload: Optional message payload sent by the agent.
        conversation_id: Optional conversation thread identifier.

    Returns:
        A list of message documents ready for persistence.
    """
    try:
        if not chat_session_id or not agent_id:
            logger.warning("chat_session_id and agent_id are required to create messages")
            return []

        messages: list[Dict[str, Any]] = []
        for payload in (user_message_payload, agent_message_payload):
            message_doc = build_chat_message_document_from_payload(
                payload, chat_session_id, agent_id, conversation_id
            )
            if message_doc:
                messages.append(message_doc)

        return messages

    except Exception as e:
        logger.error(f"Error while creating chat messages: {str(e)}")
        return []


async def create_and_store_chat_messages(
    chat_session_id: str,
    agent_id: str,
    user_message_payload: Dict[str, Any] | None = None,
    agent_message_payload: Dict[str, Any] | None = None,
) -> list[Dict[str, Any]]:
    """
    Build and persist chat messages into the atlas_chat_mesages collection.

    This single service handles validation, building documents, and storing them.
    Returns the stored documents with inserted ids stringified. Returns an empty
    list if nothing was stored.
    """
    try:
        if not chat_session_id or not agent_id:
            logger.warning("chat_session_id and agent_id are required to create messages")
            return []
        
        chatData = {
            "chat_session_id": chat_session_id,
            "agent_id": agent_id
        }
        chat_session_data = await get_chat_session_data(chatData)

        # Extract conversation_id from the session document
        conversation_id = chat_session_data.get("conversation_id") if chat_session_data else None

        logger.info(f"Creating and storing chat messages for chat_session_id={chat_session_id} and agent_id={agent_id} conversation_id={conversation_id}")

        messages = build_chat_message_documents(
            chat_session_id,
            agent_id,
            user_message_payload=user_message_payload,
            agent_message_payload=agent_message_payload,
            conversation_id=conversation_id,
        )

        if not messages:
            return []

        collection = get_collection("atlas_chat_mesages")
        result = await collection.insert_many(messages)

        # Attach inserted ids for downstream use.
        inserted_ids = result.inserted_ids if hasattr(result, "inserted_ids") else []
        for doc, inserted_id in zip(messages, inserted_ids):
            doc["_id"] = str(inserted_id)

        # Update last_message_at on the chat session for sort-by-recency queries
        now = datetime.datetime.now(datetime.timezone.utc)
        sessions_collection = get_collection("atlas_chat_sessions")
        await sessions_collection.update_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"$set": {"last_message_at": now}}
        )

        logger.info(
            "Stored %d chat message(s) for chat_session_id=%s and agent_id=%s",
            len(messages),
            chat_session_id,
            agent_id,
        )

        user_stored = next((doc for doc in messages if doc.get("role") == "user"), None)
        if user_stored:
            await maybe_record_visitor_first_message_audit(
                agent_id,
                chat_session_id,
                user_stored.get("created_at"),
            )

        return messages

    except Exception as e:
        logger.error(f"Error while creating and storing chat messages: {str(e)}")
        return []


async def maybe_record_visitor_first_message_audit(
    agent_id: str,
    chat_session_id: str,
    message_created_at: datetime.datetime | None = None,
) -> bool:
    """
    Record visitor_first_message audit once per session (idempotent via first_message_at).
    """
    try:
        if not agent_id or not chat_session_id:
            return False

        timestamp = coerce_utc_datetime(message_created_at)
        sessions_collection = get_collection("atlas_chat_sessions")
        result = await sessions_collection.update_one(
            {
                "chat_session_id": chat_session_id,
                "agent_id": agent_id,
                "$or": [
                    {"first_message_at": {"$exists": False}},
                    {"first_message_at": None},
                ],
            },
            {"$set": {"first_message_at": timestamp}},
        )
        if result.modified_count != 1:
            return False

        from services.elysium_atlas_services.atlas_chat_session_audit_services import (
            AUDIT_ACTOR_VISITOR,
            AUDIT_EVENT_VISITOR_FIRST_MESSAGE,
            record_chat_session_audit,
        )

        await record_chat_session_audit(
            agent_id,
            chat_session_id,
            AUDIT_EVENT_VISITOR_FIRST_MESSAGE,
            actor_type=AUDIT_ACTOR_VISITOR,
            occurred_at=timestamp,
        )
        return True

    except Exception as e:
        logger.error(f"Error in maybe_record_visitor_first_message_audit: {str(e)}")
        return False

async def rotate_conversation_id(agent_id: str, chat_session_id: str) -> Dict[str, Any] | None:
    """
    Generate a fresh conversation_id UUID and persist it on the atlas_chat_sessions
    document identified by agent_id + chat_session_id.

    Returns the updated document fields (chat_session_id, agent_id, conversation_id)
    or None if the document was not found or an error occurred.
    """
    try:
        if not agent_id or not chat_session_id:
            logger.warning("agent_id and chat_session_id are required to rotate conversation_id")
            return None

        collection = get_collection("atlas_chat_sessions")

        document = await collection.find_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"_id": 1}
        )
        if not document:
            logger.warning(
                f"No chat session found for chat_session_id={chat_session_id} agent_id={agent_id}"
            )
            return None

        new_conversation_id = str(uuid.uuid4())

        await collection.update_one(
            {"_id": document["_id"]},
            {"$set": {"conversation_id": new_conversation_id}}
        )

        logger.info(
            f"Rotated conversation_id to {new_conversation_id} for "
            f"chat_session_id={chat_session_id} agent_id={agent_id}"
        )

        return {
            "chat_session_id": chat_session_id,
            "agent_id": agent_id,
            "conversation_id": new_conversation_id,
        }

    except Exception as e:
        logger.error(f"Error in rotate_conversation_id: {str(e)}")
        return None


async def set_visitor_online_status(agent_id: str, chat_session_id: str, visitor_online: bool) -> bool:
    """
    Set the visitor_online field on an atlas_chat_sessions document.

    Args:
        agent_id: The agent identifier.
        chat_session_id: The chat session identifier.
        visitor_online: True to mark the visitor as online, False for offline.

    Returns:
        True if the document was found and updated, False otherwise.
    """
    try:
        if not agent_id or not chat_session_id:
            logger.warning("agent_id and chat_session_id are required to set visitor_online status")
            return False

        collection = get_collection("atlas_chat_sessions")

        update_fields: Dict[str, Any] = {"visitor_online": visitor_online}
        if visitor_online:
            update_fields["last_connected_at"] = datetime.datetime.now(datetime.timezone.utc)

        result = await collection.update_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"$set": update_fields}
        )

        if result.matched_count == 0:
            logger.warning(
                f"No chat session found to update visitor_online for "
                f"chat_session_id={chat_session_id} agent_id={agent_id}"
            )
            return False

        logger.info(
            f"Set visitor_online={visitor_online} for "
            f"chat_session_id={chat_session_id} agent_id={agent_id}"
        )
        return True

    except Exception as e:
        logger.error(f"Error in set_visitor_online_status: {str(e)}")
        return False


async def patch_chat_session(agent_id: str, chat_session_id: str, fields: Dict[str, Any]) -> bool:
    """
    Apply an arbitrary $set update to an atlas_chat_sessions document.

    Useful for storing supplementary data (e.g. geo_data, custom metadata)
    without needing a dedicated service function for each field.

    Args:
        agent_id: The agent identifier.
        chat_session_id: The chat session identifier.
        fields: A dict of key/value pairs to set on the document.

    Returns:
        True if the document was found and updated, False otherwise.
    """
    try:
        if not agent_id or not chat_session_id or not fields:
            logger.warning("patch_chat_session: agent_id, chat_session_id and fields are all required")
            return False

        collection = get_collection("atlas_chat_sessions")
        result = await collection.update_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"$set": fields}
        )

        if result.matched_count == 0:
            logger.warning(
                f"patch_chat_session: no document found for "
                f"chat_session_id={chat_session_id} agent_id={agent_id}"
            )
            return False

        logger.info(
            f"patch_chat_session: updated fields {list(fields.keys())} for "
            f"chat_session_id={chat_session_id} agent_id={agent_id}"
        )
        return True

    except Exception as e:
        logger.error(f"Error in patch_chat_session: {str(e)}")
        return False


async def get_chat_session_in_conversation_with(
    agent_id: str,
    chat_session_id: str,
) -> str | None:
    """Read the persisted human takeover handler from atlas_chat_sessions."""
    try:
        if not agent_id or not chat_session_id:
            return None

        collection = get_collection("atlas_chat_sessions")
        doc = await collection.find_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"in_conversation_with": 1, "_id": 0},
        )
        if not doc:
            return None

        handler = doc.get("in_conversation_with")
        return str(handler) if handler is not None else None

    except Exception as e:
        logger.error(f"Error in get_chat_session_in_conversation_with: {str(e)}")
        return None


async def set_chat_session_in_conversation_with(
    agent_id: str,
    chat_session_id: str,
    user_id: str | None,
) -> bool:
    """Persist human takeover handler and session status on atlas_chat_sessions."""
    from config.atlas_chat_config import resolve_chat_session_status_for_takeover

    return await patch_chat_session(
        agent_id,
        chat_session_id,
        {
            "in_conversation_with": user_id,
            "status": resolve_chat_session_status_for_takeover(user_id),
        },
    )


async def resolve_active_conversation_handler(
    agent_id: str,
    chat_session_id: str,
) -> str | None:
    """Resolve who holds human takeover for a session (Mongo source of truth)."""
    handler = await get_chat_session_in_conversation_with(agent_id, chat_session_id)
    return str(handler) if handler else None


async def persist_in_conversation_with(
    agent_id: str,
    chat_session_id: str,
    user_id: str | None,
    *,
    actor_user_id: str | None = None,
) -> bool:
    """
    Update in_conversation_with in Mongo. Returns True when the visitor is online (for emits).
    """
    from services.elysium_atlas_services.atlas_presence_services import (
        update_visitor_conversation_status,
    )
    from services.elysium_atlas_services.atlas_chat_session_audit_services import (
        AUDIT_ACTOR_TEAM_MEMBER,
        AUDIT_EVENT_TAKEOVER_RELEASED,
        AUDIT_EVENT_TAKEOVER_STARTED,
        record_chat_session_audit,
    )

    previous_handler = await get_chat_session_in_conversation_with(agent_id, chat_session_id)

    visitor_online = await update_visitor_conversation_status(agent_id, chat_session_id, user_id)
    await set_chat_session_in_conversation_with(agent_id, chat_session_id, user_id)

    if user_id and user_id != previous_handler:
        await record_chat_session_audit(
            agent_id,
            chat_session_id,
            AUDIT_EVENT_TAKEOVER_STARTED,
            actor_user_id=actor_user_id or user_id,
            actor_type=AUDIT_ACTOR_TEAM_MEMBER,
            metadata={
                "previous_in_conversation_with": previous_handler,
                "in_conversation_with": user_id,
            },
        )
        from services.elysium_atlas_services.human_handover_services import (
            assign_handover_on_takeover,
        )

        await assign_handover_on_takeover(agent_id, chat_session_id, user_id)
    elif user_id is None and previous_handler:
        await record_chat_session_audit(
            agent_id,
            chat_session_id,
            AUDIT_EVENT_TAKEOVER_RELEASED,
            actor_user_id=actor_user_id or previous_handler,
            actor_type=AUDIT_ACTOR_TEAM_MEMBER,
            metadata={"released_in_conversation_with": previous_handler},
        )
        from services.elysium_atlas_services.human_handover_services import (
            reset_handover_after_takeover_release,
        )

        await reset_handover_after_takeover_release(agent_id, chat_session_id)

    return visitor_online


async def mark_chat_session_resolved(
    agent_id: str,
    chat_session_id: str,
    *,
    resolved_by: str | None = None,
    allow_privileged_resolve: bool = False,
) -> dict[str, Any]:
    """
    Mark a chat session as resolved.

    Team members with active takeover may always resolve.
    Owner/admin may resolve without holding takeover (including AI-only sessions).

    Clears any active human takeover and notifies the visitor when online.

    Returns a result dict with success, status, and visitor_online for emits.
    """
    from config.atlas_chat_config import CHAT_SESSION_STATUS_RESOLVED
    from services.elysium_atlas_services.atlas_presence_services import (
        update_visitor_conversation_status,
    )
    from services.elysium_atlas_services.atlas_chat_session_audit_services import (
        AUDIT_ACTOR_TEAM_MEMBER,
        AUDIT_EVENT_SESSION_RESOLVED,
        AUDIT_EVENT_TAKEOVER_RELEASED,
        record_chat_session_audit,
    )

    try:
        if not agent_id or not chat_session_id:
            return {"success": False, "message": "agent_id and chat_session_id are required"}

        if not resolved_by:
            return {"success": False, "message": "resolved_by user_id is required"}

        collection = get_collection("atlas_chat_sessions")
        session = await collection.find_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"status": 1, "in_conversation_with": 1, "resolved_at": 1},
        )
        if not session:
            return {"success": False, "message": "Chat session not found"}

        if session.get("status") == CHAT_SESSION_STATUS_RESOLVED:
            return {
                "success": True,
                "message": "Session is already resolved",
                "status": CHAT_SESSION_STATUS_RESOLVED,
                "already_resolved": True,
                "visitor_online": False,
            }

        active_handler = await resolve_active_conversation_handler(agent_id, chat_session_id)
        is_active_handler = bool(active_handler and active_handler == str(resolved_by))

        if not is_active_handler and not allow_privileged_resolve:
            return {
                "success": False,
                "message": "Only the team member who has taken over this conversation can mark it as resolved",
                "in_conversation_with": active_handler,
            }

        previous_handler = active_handler
        resolved_by_privileged = allow_privileged_resolve and not is_active_handler

        from services.elysium_atlas_services.human_handover_services import (
            reset_handover_after_takeover_release,
        )

        await reset_handover_after_takeover_release(agent_id, chat_session_id)

        now = datetime.datetime.now(datetime.timezone.utc)
        visitor_online = False
        if previous_handler:
            visitor_online = await update_visitor_conversation_status(agent_id, chat_session_id, None)
            await record_chat_session_audit(
                agent_id,
                chat_session_id,
                AUDIT_EVENT_TAKEOVER_RELEASED,
                actor_user_id=resolved_by,
                actor_type=AUDIT_ACTOR_TEAM_MEMBER,
                metadata={
                    "released_in_conversation_with": previous_handler,
                    "released_via": "session_resolved",
                    "resolved_by_privileged": resolved_by_privileged,
                },
            )

        await collection.update_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {
                "$set": {
                    "status": CHAT_SESSION_STATUS_RESOLVED,
                    "in_conversation_with": None,
                    "resolved_at": now,
                    "resolved_by": str(resolved_by) if resolved_by is not None else None,
                }
            },
        )

        audit_row = await record_chat_session_audit(
            agent_id,
            chat_session_id,
            AUDIT_EVENT_SESSION_RESOLVED,
            actor_user_id=resolved_by,
            actor_type=AUDIT_ACTOR_TEAM_MEMBER,
            occurred_at=now,
            metadata={
                "previous_status": session.get("status"),
                "had_active_takeover": bool(previous_handler),
                "previous_in_conversation_with": previous_handler,
                "resolved_by_privileged": resolved_by_privileged,
            },
        )

        logger.info(
            "Marked chat session resolved: chat_session_id=%s agent_id=%s resolved_by=%s",
            chat_session_id,
            agent_id,
            resolved_by,
        )
        return {
            "success": True,
            "message": "Chat session marked as resolved",
            "status": CHAT_SESSION_STATUS_RESOLVED,
            "resolved_at": format_utc_datetime_for_client(now),
            "resolved_by": str(resolved_by) if resolved_by is not None else None,
            "visitor_online": visitor_online,
            "had_active_takeover": bool(previous_handler),
            "resolved_by_privileged": resolved_by_privileged,
            "audit": audit_row,
        }

    except Exception as e:
        logger.error(f"Error in mark_chat_session_resolved: {str(e)}", exc_info=True)
        return {"success": False, "message": "Failed to mark chat session as resolved"}


async def reactivate_chat_session_if_resolved(
    agent_id: str,
    chat_session_id: str,
) -> dict[str, Any] | None:
    """
    When a resolved session receives a new visitor message, move status back to active.

    Returns reactivation payload when status changed, else None.
    """
    from config.atlas_chat_config import CHAT_SESSION_STATUS_ACTIVE, CHAT_SESSION_STATUS_RESOLVED
    from services.elysium_atlas_services.atlas_chat_session_audit_services import (
        AUDIT_ACTOR_VISITOR,
        AUDIT_EVENT_SESSION_REACTIVATED,
        record_chat_session_audit,
    )

    try:
        if not agent_id or not chat_session_id:
            return None

        collection = get_collection("atlas_chat_sessions")
        session = await collection.find_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {"status": 1, "resolved_at": 1, "resolved_by": 1},
        )
        if not session or session.get("status") != CHAT_SESSION_STATUS_RESOLVED:
            return None

        now = datetime.datetime.now(datetime.timezone.utc)
        await collection.update_one(
            {"chat_session_id": chat_session_id, "agent_id": agent_id},
            {
                "$set": {"status": CHAT_SESSION_STATUS_ACTIVE},
                "$unset": {"resolved_at": "", "resolved_by": ""},
            },
        )

        audit_row = await record_chat_session_audit(
            agent_id,
            chat_session_id,
            AUDIT_EVENT_SESSION_REACTIVATED,
            actor_type=AUDIT_ACTOR_VISITOR,
            occurred_at=now,
            metadata={
                "previous_status": CHAT_SESSION_STATUS_RESOLVED,
                "previous_resolved_at": format_utc_datetime_for_client(session["resolved_at"])
                if isinstance(session.get("resolved_at"), datetime.datetime)
                else session.get("resolved_at"),
                "previous_resolved_by": session.get("resolved_by"),
            },
        )

        logger.info(
            "Reactivated resolved chat session: chat_session_id=%s agent_id=%s",
            chat_session_id,
            agent_id,
        )
        return {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "status": CHAT_SESSION_STATUS_ACTIVE,
            "previous_status": CHAT_SESSION_STATUS_RESOLVED,
            "reactivated_at": format_utc_datetime_for_client(now),
            "audit": audit_row,
        }

    except Exception as e:
        logger.error(f"Error in reactivate_chat_session_if_resolved: {str(e)}", exc_info=True)
        return None


async def get_chat_message_by_object_id(
    message_object_id: str,
    agent_id: str,
    chat_session_id: str,
) -> Dict[str, Any] | None:
    """Fetch a single chat message scoped to agent_id and chat_session_id."""
    if not message_object_id or not agent_id or not chat_session_id:
        return None
    if not ObjectId.is_valid(message_object_id):
        return None

    collection = get_collection("atlas_chat_mesages")
    return await collection.find_one(
        {
            "_id": ObjectId(message_object_id),
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
        }
    )


async def resolve_chat_message_identifier(
    message_identifier: str,
    agent_id: str,
    chat_session_id: str,
) -> Dict[str, Any] | None:
    """
    Resolve a message by Mongo _id or by the client UUID stored in message_id.
    """
    if not message_identifier or not agent_id or not chat_session_id:
        return None

    collection = get_collection("atlas_chat_mesages")
    base_query = {"agent_id": agent_id, "chat_session_id": chat_session_id}

    if ObjectId.is_valid(message_identifier):
        doc = await collection.find_one({**base_query, "_id": ObjectId(message_identifier)})
        if doc:
            return doc

    return await collection.find_one({**base_query, "message_id": message_identifier})


def stored_message_metadata(stored_doc: Dict[str, Any] | None) -> Dict[str, Any]:
    """Build socket/API metadata from a persisted chat message document."""
    if not stored_doc:
        return {}

    metadata: Dict[str, Any] = {}
    mongo_id = stored_doc.get("_id")
    if mongo_id is not None:
        metadata["_id"] = str(mongo_id)

    client_message_id = stored_doc.get("message_id")
    if client_message_id is not None:
        metadata["message_id"] = client_message_id

    role = stored_doc.get("role")
    if role is not None:
        metadata["role"] = role

    created_at = stored_doc.get("created_at")
    if isinstance(created_at, datetime.datetime):
        metadata["created_at"] = format_utc_datetime_for_client(created_at)
    elif created_at is not None:
        metadata["created_at"] = created_at

    return metadata


def _serialize_session_datetime(value) -> str | None:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value


async def session_has_prior_team_member_conversation(
    agent_id: str,
    chat_session_id: str,
) -> bool:
    """
    True when the session qualifies for team-member-chat-sessions
    (at least one team member has participated — team_member_ids is non-empty).
    """
    try:
        if not agent_id or not chat_session_id:
            return False

        collection = get_collection("atlas_chat_sessions")
        doc = await collection.find_one(
            {"agent_id": agent_id, "chat_session_id": chat_session_id},
            {"team_member_ids": 1},
        )
        if not doc:
            return False

        team_member_ids = doc.get("team_member_ids") or []
        return isinstance(team_member_ids, list) and len(team_member_ids) > 0

    except Exception as e:
        logger.error(f"Error checking prior team member conversation: {str(e)}")
        return False


async def get_last_chat_message_for_session(
    agent_id: str,
    chat_session_id: str,
    conversation_id: str | None = None,
) -> Dict[str, Any] | None:
    """Fetch the most recent message in a conversation thread."""
    if not agent_id or not chat_session_id:
        return None

    query: Dict[str, Any] = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
    }
    if conversation_id:
        query["conversation_id"] = conversation_id

    collection = get_collection("atlas_chat_mesages")
    msg = await collection.find_one(query, sort=[("created_at", -1)])
    return serialize_chat_message_for_client(msg) if msg else None


async def build_messaging_session_update_payload(
    agent_id: str,
    chat_session_id: str,
    last_message: Dict[str, Any] | None = None,
) -> Dict[str, Any] | None:
    """
    Build a team-member-chat-sessions row for real-time Messaging updates.
    Returns None when the session is not eligible (no prior team member conversation).
    """
    try:
        if not agent_id or not chat_session_id:
            return None

        if not await session_has_prior_team_member_conversation(agent_id, chat_session_id):
            return None

        collection = get_collection("atlas_chat_sessions")
        doc = await collection.find_one(
            {"agent_id": agent_id, "chat_session_id": chat_session_id},
        )
        if not doc:
            return None

        conversation_id = doc.get("conversation_id")
        if last_message is None:
            last_message = await get_last_chat_message_for_session(
                agent_id, chat_session_id, conversation_id
            )

        unread_count = await count_unread_visitor_messages(
            agent_id, chat_session_id, conversation_id
        )

        session_fields = (
            "chat_session_id",
            "alias_name",
            "last_message_at",
            "visitor_online",
            "last_connected_at",
            "geo_data",
        )
        payload: Dict[str, Any] = {"agent_id": agent_id, "conversation_mode": "ai"}
        for field in session_fields:
            payload[field] = _serialize_session_datetime(doc.get(field))

        payload["last_message"] = last_message
        payload["has_unread_messages"] = unread_count > 0
        payload["unread_visitor_message_count"] = unread_count
        return payload

    except Exception as e:
        logger.error(f"Error building messaging session update payload: {str(e)}")
        return None


async def count_unread_visitor_messages(
    agent_id: str,
    chat_session_id: str,
    conversation_id: str | None = None,
) -> int:
    """
    Count visitor messages (role=user) without read_at in the current conversation thread.
    """
    try:
        if not agent_id or not chat_session_id:
            return 0

        query: Dict[str, Any] = {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "role": "user",
            "$or": [{"read_at": {"$exists": False}}, {"read_at": None}],
        }
        if conversation_id:
            query["conversation_id"] = conversation_id

        collection = get_collection("atlas_chat_mesages")
        return await collection.count_documents(query)

    except Exception as e:
        logger.error(f"Error counting unread visitor messages: {str(e)}")
        return 0


async def mark_chat_message_as_read(
    message_identifier: str,
    agent_id: str,
    chat_session_id: str,
    read_by: str | None = None,
) -> Dict[str, Any]:
    """
    Set read_at on an atlas_chat_mesages document (UTC datetime).
    message_identifier may be the Mongo _id or the client UUID in message_id.
    read_by: user _id of the first reader (audit); stored only on the first read.
    Idempotent: preserves the first read_at and read_by if already set.
    """
    try:
        if not message_identifier or not agent_id or not chat_session_id:
            return {
                "success": False,
                "message": "message_id, agent_id and chat_session_id are required",
            }

        message = await resolve_chat_message_identifier(
            message_identifier, agent_id, chat_session_id
        )
        if not message:
            return {"success": False, "message": "Message not found"}

        message_object_id = str(message["_id"])
        collection = get_collection("atlas_chat_mesages")
        existing_read_at = message.get("read_at")
        if existing_read_at:
            read_at = coerce_utc_datetime(existing_read_at)
            stored_read_by = message.get("read_by")
            if stored_read_by is not None:
                stored_read_by = str(stored_read_by)
        else:
            read_at = datetime.datetime.now(datetime.timezone.utc)
            update_fields: Dict[str, Any] = {"read_at": read_at}
            if read_by is not None:
                update_fields["read_by"] = str(read_by)
            await collection.update_one(
                {"_id": message["_id"]},
                {"$set": update_fields},
            )
            stored_read_by = str(read_by) if read_by is not None else None

        logger.info(
            "Marked message %s as read for chat_session_id=%s agent_id=%s read_by=%s",
            message_object_id,
            chat_session_id,
            agent_id,
            stored_read_by,
        )

        data: Dict[str, Any] = {
            "_id": message_object_id,
            "message_id": message.get("message_id"),
            "read_at": format_utc_datetime_for_client(read_at),
        }
        if stored_read_by is not None:
            data["read_by"] = stored_read_by

        return {
            "success": True,
            "message": "Message marked as read",
            "data": data,
        }

    except Exception as e:
        logger.error(f"Error in mark_chat_message_as_read: {str(e)}")
        return {"success": False, "message": "Failed to mark message as read"}