from typing import Dict, Any, List
from logging_config import get_logger
from services.mongo_services import get_collection
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
import datetime
from bson import ObjectId
import random
import asyncio
import uuid

from config.atlas_metadata_extraction_models import EnhancedSemanticMessage
from services.open_ai_services import openai_structured_output

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
                document["created_at"] = document["created_at"].isoformat()
            if "last_message_at" in document and document["last_message_at"]:
                document["last_message_at"] = document["last_message_at"].isoformat()

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

        # Find messages, sort by created_at ascending, limit
        cursor = collection.find(
            query,
            {"message_id": 1, "role": 1, "content": 1, "created_at": 1, "conversation_id": 1, "_id": 0}
        ).sort("created_at", 1).limit(limit)

        messages = await cursor.to_list(length=None)

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
) -> list[Dict[str, Any]]:
    """
    Build message documents for the provided payloads.

    Args:
        chat_session_id: The chat session identifier.
        agent_id: The agent identifier.
        user_message_payload: Optional message payload sent by the user.
        agent_message_payload: Optional message payload sent by the agent.

    Returns:
        A list of message documents ready for persistence.
    """
    try:
        if not chat_session_id or not agent_id:
            logger.warning("chat_session_id and agent_id are required to create messages")
            return []

        messages: list[Dict[str, Any]] = []

        def _build_message_document(payload: Dict[str, Any] | None) -> Dict[str, Any] | None:
            if not payload:
                return None
            if not isinstance(payload, dict):
                logger.warning("Invalid payload type for chat message; expected dict")
                return None

            message_id = payload.get("message_id")
            role = payload.get("role")
            content = payload.get("content")
            created_at = payload.get("created_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()

            if not role or content is None:
                logger.warning("Missing role or content in chat message payload")
                return None

            doc = {
                "chat_session_id": chat_session_id,
                "agent_id": agent_id,
                "message_id": message_id,
                "role": role,
                "content": content,
                "created_at": created_at,
            }

            # Add enhanced_message if present
            if "enhanced_message" in payload:
                doc["enhanced_message"] = payload["enhanced_message"]

            return doc

        for payload in (user_message_payload, agent_message_payload):
            message_doc = _build_message_document(payload)
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

        messages: list[Dict[str, Any]] = []

        def _build_message_document(payload: Dict[str, Any] | None) -> Dict[str, Any] | None:
            if not payload:
                return None
            if not isinstance(payload, dict):
                logger.warning("Invalid payload type for chat message; expected dict")
                return None

            message_id = payload.get("message_id")
            role = payload.get("role")
            content = payload.get("content")
            created_at = payload.get("created_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()

            if not role or content is None:
                logger.warning("Missing role or content in chat message payload")
                return None

            doc = {
                "chat_session_id": chat_session_id,
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "role": role,
                "content": content,
                "created_at": created_at,
            }

            # Add enhanced_message if present
            if "enhanced_message" in payload:
                doc["enhanced_message"] = payload["enhanced_message"]

            return doc

        for payload in (user_message_payload, agent_message_payload):
            message_doc = _build_message_document(payload)
            if message_doc:
                messages.append(message_doc)

        if not messages:
            return []

        collection = get_collection("atlas_chat_mesages")
        result = await collection.insert_many(messages)

        # Attach inserted ids for downstream use.
        inserted_ids = result.inserted_ids if hasattr(result, "inserted_ids") else []
        for doc, inserted_id in zip(messages, inserted_ids):
            doc["_id"] = str(inserted_id)

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


async def enhance_user_message(message: str, chat_history: List[Dict[str, Any]], model = "gpt-4.1-mini") -> str:
    """
    Enhance a user's message using prior chat history to produce
    a self-contained, semantically clear query suitable for embeddings or RAG.
    """
    try:

        # Build compact chat history text (important: avoid token bloat)
        formatted_history = []
        for item in chat_history:
            role = item.get("role", "user")
            content = item.get("content", "")
            formatted_history.append(f"{role.upper()}: {content}")

        chat_history_text = "\n".join(formatted_history)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert at rewriting user messages into semantically precise, "
                    "self-contained queries by resolving context from chat history.\n\n"
                    "CORE PRINCIPLES:\n"
                    "1. RESOLVE REFERENCES: Transform pronouns, demonstratives, and contextual words:\n"
                    "   - 'it' → the specific thing being referenced\n"
                    "   - 'that' → the specific concept mentioned\n"
                    "   - 'again' → repeat the specific question/topic\n"
                    "   - 'more' → more about the specific subject\n\n"
                    "2. MAINTAIN SEMANTIC PRECISION: Don't generalize - be as specific as the context allows\n"
                    "3. PRESERVE USER INTENT: Keep the user's exact informational need\n"
                    "4. USE CHAT HISTORY STRATEGICALLY: Only reference what's directly relevant to resolve ambiguity\n\n"
                    "EXAMPLES:\n"
                    "- If user asks 'who am I talking to?' then later says 'tell me again' → 'Who am I talking to?'\n"
                    "- If discussing Python, user says 'explain it more' → 'Explain Python in more detail'\n"
                    "- User says 'what about that other approach?' → 'What about [specific approach mentioned]?'\n\n"
                    "OUTPUT: Only the rewritten message, nothing else."
                )
            },
            {
                "role": "user",
                "content": (
                    f"CHAT HISTORY:\n{chat_history_text}\n\n"
                    f"USER'S LATEST MESSAGE: \"{message}\"\n\n"
                    "Transform this into a self-contained, semantically precise query by resolving any contextual references from the chat history:"
                )
            }
        ]

        logger.debug("Enhancing user message using LLM")

        response = await openai_structured_output(
            model=model,
            messages=messages,
            response_format=EnhancedSemanticMessage
        )

        enhanced_message = response.get("enhanced_message", "").strip()

        return enhanced_message if enhanced_message else message

    except Exception as e:
        logger.error(f"Error in enhance_user_message: {str(e)}")
        return message


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
            update_fields["last_connected_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")

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