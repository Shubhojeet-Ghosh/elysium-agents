from typing import Dict, Any, List
from logging_config import get_logger
from services.mongo_services import get_collection
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
import datetime
from bson import ObjectId
import random
import asyncio
import uuid

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
            # Convert ObjectId and datetime fields
            document["_id"] = str(document["_id"])
            if "created_at" in document and document["created_at"]:
                v = document["created_at"]
                document["created_at"] = v.isoformat() if isinstance(v, datetime.datetime) else v
            if "last_message_at" in document and document["last_message_at"]:
                v = document["last_message_at"]
                document["last_message_at"] = v.isoformat() if isinstance(v, datetime.datetime) else v
            if "last_connected_at" in document and document["last_connected_at"]:
                v = document["last_connected_at"]
                document["last_connected_at"] = v.isoformat() if isinstance(v, datetime.datetime) else v

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
            document["created_at"] = document["created_at"].isoformat()
            document["last_message_at"] = document["last_message_at"].isoformat()
            
            # For new session, messages will be empty
            document["messages"] = []
            
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

        return messages

    except Exception as e:
        logger.error(f"Error while creating and storing chat messages: {str(e)}")
        return []

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