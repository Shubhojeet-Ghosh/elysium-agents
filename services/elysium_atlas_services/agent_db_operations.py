from datetime import datetime, timezone
from typing import Any, Dict
from logging_config import get_logger
from services.mongo_services import get_collection
from services.redis_services import cache_get, cache_set
from bson import ObjectId

logger = get_logger()


async def get_agent_by_id(agent_id: str) -> Dict[str, Any] | None:
    """
    Retrieve an agent document from the 'atlas_agents' collection by agent_id.

    Args:
        agent_id: The ID of the agent to retrieve.

    Returns:
        Dict[str, Any] | None: The agent document if found, None otherwise.
    """
    try:
        logger.info(f"Retrieving agent document for agent_id: {agent_id}")

        collection = get_collection("atlas_agents")

        # Convert agent_id to ObjectId if it's a string
        if isinstance(agent_id, str):
            agent_id = ObjectId(agent_id)

        # Find the agent document
        agent = await collection.find_one({"_id": agent_id})

        if agent:
            # Convert ObjectId and datetime fields to strings
            if "_id" in agent:
                agent["_id"] = str(agent["_id"])
            if "created_at" in agent and agent["created_at"]:
                agent["created_at"] = agent["created_at"].isoformat()
            if "updated_at" in agent and agent["updated_at"]:
                agent["updated_at"] = agent["updated_at"].isoformat()
            
            logger.info(f"Retrieved agent document for agent_id: {agent_id}")
            return agent
        else:
            logger.warning(f"No agent found for agent_id: {agent_id}")
            return None

    except Exception as e:
        logger.error(f"Error retrieving agent for agent_id {agent_id}: {e}")
        return None


async def get_agent_owner_user_id(agent_id: str) -> str | None:
    """
    Retrieve only the owner_user_id for a given agent_id from atlas_agents.
    Result is cached in Redis with a 30-day TTL to avoid repeated DB lookups.

    Args:
        agent_id: The string ID of the agent (_id in the collection).

    Returns:
        The owner_user_id string, or None if not found.
    """
    CACHE_KEY = f"atlas:agent_owner:{agent_id}"
    CACHE_TTL = 60 * 60 * 24 * 30  # 30 days

    try:
        # 1. Check Redis cache first
        cached = cache_get(CACHE_KEY)
        if cached is not None:
            logger.info(f"Cache hit - owner_user_id for agent_id {agent_id}: {cached}")
            return cached

        # 2. Cache miss — query MongoDB
        logger.info(f"Cache miss - fetching owner_user_id from DB for agent_id: {agent_id}")
        collection = get_collection("atlas_agents")
        agent_object_id = ObjectId(agent_id) if isinstance(agent_id, str) else agent_id
        doc = await collection.find_one(
            {"_id": agent_object_id},
            {"owner_user_id": 1, "_id": 0}
        )

        if doc:
            owner_user_id = doc.get("owner_user_id")
            logger.info(f"owner_user_id for agent_id {agent_id}: {owner_user_id}")
            # 3. Store in Redis for future calls
            cache_set({CACHE_KEY: owner_user_id}, ex=CACHE_TTL)
            return owner_user_id
        else:
            logger.warning(f"No agent found for agent_id: {agent_id} when fetching owner_user_id")
            return None

    except Exception as e:
        logger.error(f"Error fetching owner_user_id for agent_id {agent_id}: {e}")
        return None


async def get_agent_fields_by_id(agent_id: str, fields: list[str]) -> Dict[str, Any] | None:
    """
    Retrieve specific fields of an agent document from the 'atlas_agents' collection by agent_id.

    Args:
        agent_id: The ID of the agent to retrieve.
        fields: List of field names to retrieve.

    Returns:
        Dict[str, Any] | None: The agent document with only the specified fields if found, None otherwise.
    """
    try:
        logger.info(f"Retrieving agent fields {fields} for agent_id: {agent_id}")

        collection = get_collection("atlas_agents")

        # Convert agent_id to ObjectId if it's a string
        if isinstance(agent_id, str):
            agent_id = ObjectId(agent_id)

        # Find the agent document
        agent = await collection.find_one({"_id": agent_id})

        if agent:
            # Convert ObjectId and datetime fields to strings
            if "_id" in agent:
                agent["_id"] = str(agent["_id"])
            if "created_at" in agent and agent["created_at"]:
                agent["created_at"] = agent["created_at"].isoformat()
            if "updated_at" in agent and agent["updated_at"]:
                agent["updated_at"] = agent["updated_at"].isoformat()
            
            # Create result with only requested fields, set missing ones to None
            result = {}
            for field in fields:
                result[field] = agent.get(field, None)
            
            logger.info(f"Retrieved agent fields for agent_id: {agent_id}")
            return result
        else:
            logger.warning(f"No agent found for agent_id: {agent_id}")
            return None

    except Exception as e:
        logger.error(f"Error retrieving agent fields for agent_id {agent_id}: {e}")
        return None


async def update_agent_current_task(agent_id: str, current_task: str) -> bool:
    """
    Update the `agent_current_task` field for a specific agent document in the 'atlas_agents' collection.

    Args:
        agent_id: The ID of the agent to update.
        current_task: The current task to set for the agent.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        collection = get_collection("atlas_agents")
        current_time = datetime.now(timezone.utc)

        # Convert agent_id to ObjectId if it's a strinzg
        if isinstance(agent_id, str):
            agent_id = ObjectId(agent_id)

        # Update the agent document with the new current task
        result = await collection.update_one(
            {"_id": agent_id},
            {"$set": {"agent_current_task": current_task, "updated_at": current_time}}
        )

        if result.modified_count > 0:
            logger.info(f"Updated agent_current_task for agent_id: {agent_id} to '{current_task}'")
            return True
        else:
            logger.warning(f"No document found to update for agent_id: {agent_id}")
            return False

    except Exception as e:
        logger.error(f"Error updating agent_current_task for agent_id {agent_id}: {e}")
        return False


async def update_agent_status(agent_id: str, agent_status: str) -> bool:
    """
    Update the `agent_status` field for a specific agent document in the 'atlas_agents' collection.

    Args:
        agent_id: The ID of the agent to update.
        agent_status: The status to set for the agent.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        collection = get_collection("atlas_agents")
        current_time = datetime.now(timezone.utc)

        # Convert agent_id to ObjectId if it's a string
        if isinstance(agent_id, str):
            agent_id = ObjectId(agent_id)

        # Update the agent document with the new status
        result = await collection.update_one(
            {"_id": agent_id},
            {"$set": {"agent_status": agent_status, "updated_at": current_time}}
        )

        if result.modified_count > 0:
            logger.info(f"Updated agent_status for agent_id: {agent_id} to '{agent_status}'")
            return True
        else:
            logger.warning(f"No document found to update for agent_id: {agent_id}")
            return False

    except Exception as e:
        logger.error(f"Error updating agent_status for agent_id {agent_id}: {e}")
        return False


async def check_agent_name_exists(owner_user_id: str, agent_name: str) -> bool:
    """
    Check if an agent with the given name already exists for the specified owner user ID.

    Args:
        owner_user_id: The ID of the owner user.
        agent_name: The name of the agent to check.

    Returns:
        bool: True if an agent with the name exists for the owner, False otherwise.
    """
    try:
        collection = get_collection("atlas_agents")
        count = await collection.count_documents({"owner_user_id": owner_user_id, "agent_name": agent_name})
        exists = count > 0
        if exists:
            logger.info(f"Agent name '{agent_name}' already exists for owner_user_id: {owner_user_id}")
        else:
            logger.info(f"Agent name '{agent_name}' does not exist for owner_user_id: {owner_user_id}")
        return exists
    except Exception as e:
        logger.error(f"Error checking agent name existence for owner_user_id {owner_user_id} and agent_name '{agent_name}': {e}")
        return False


async def update_agent_fields(agent_id: str, fields: Dict[str, Any]) -> bool:
    """
    Update or add fields for a specific agent document in the 'atlas_agents' collection.

    Args:
        agent_id: The ID of the agent to update.
        fields: A dictionary of key-value pairs to update or add.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        collection = get_collection("atlas_agents")
        current_time = datetime.now(timezone.utc)

        # Convert agent_id to ObjectId if it's a string
        if isinstance(agent_id, str):
            agent_id = ObjectId(agent_id)

        # Prepare the update dict
        update_dict = {**fields, "updated_at": current_time}

        # Update the agent document
        result = await collection.update_one(
            {"_id": agent_id},
            {"$set": update_dict}
        )

        if result.modified_count > 0:
            logger.info(f"Updated fields for agent_id: {agent_id} with {fields}")
            return True
        else:
            logger.warning(f"No document found to update for agent_id: {agent_id}")
            return False

    except Exception as e:
        logger.error(f"Error updating fields for agent_id {agent_id}: {e}")
        return False


async def set_url_statuses_to_indexing(agent_id: str, links: list[str], status: str = "indexing") -> bool:
    """
    Update the status of URL documents for the given agent_id and list of URLs.
    Creates new documents for URLs that don't exist with page_type as empty string.

    Args:
        agent_id: The ID of the agent.
        links: List of URLs to update or create.
        status: The status to set (default: "indexing").

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        collection = get_collection("atlas_agent_urls")
        current_time = datetime.now(timezone.utc)

        updated_count = 0
        for link in links:
            # Upsert: update if exists, insert if not
            result = await collection.update_one(
                {"agent_id": str(agent_id), "url": link},
                {
                    "$set": {"status": status, "updated_at": current_time},
                    "$setOnInsert": {"created_at": current_time, "page_type": ""}
                },
                upsert=True
            )
            if result.modified_count > 0 or result.upserted_id:
                updated_count += 1

        if updated_count > 0:
            logger.info(f"Updated/created {updated_count} URL documents to '{status}' for agent_id: {agent_id}")
            return True
        else:
            logger.warning(f"No URL documents were updated or created for agent_id: {agent_id}")
            return True  # Not an error

    except Exception as e:
        logger.error(f"Error updating URL statuses for agent_id {agent_id}: {e}")
        return False


async def set_file_statuses_to_indexing(agent_id: str, files: list[dict], status: str = "indexing") -> bool:
    """
    Update the status of file documents for the given agent_id and list of files.
    Creates new documents for files that don't exist.

    Args:
        agent_id: The ID of the agent.
        files: List of file dictionaries containing file details.
        status: The status to set (default: "indexing").

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        collection = get_collection("atlas_agent_files")
        current_time = datetime.now(timezone.utc)

        updated_count = 0
        for file in files:
            file_key = file.get("file_key")
            if not file_key:
                logger.warning(f"File key missing for file: {file}")
                continue

            # Prepare the document data
            doc_data = {
                "agent_id": str(agent_id),
                "file_name": file.get("file_name", ""),
                "file_key": file_key,
                "status": status,
                "updated_at": current_time
            }

            # Add optional fields if available
            if "cdn_url" in file:
                doc_data["cdn_url"] = file["cdn_url"]
            if "file_source" in file:
                doc_data["file_source"] = file["file_source"]

            # Upsert: update if exists, insert if not
            result = await collection.update_one(
                {"agent_id": str(agent_id), "file_key": file_key},
                {
                    "$set": doc_data,
                    "$setOnInsert": {"created_at": current_time}
                },
                upsert=True
            )
            if result.modified_count > 0 or result.upserted_id:
                updated_count += 1

        if updated_count > 0:
            logger.info(f"Updated/created {updated_count} file documents to '{status}' for agent_id: {agent_id}")
            return True
        else:
            logger.warning(f"No file documents were updated or created for agent_id: {agent_id}")
            return True  # Not an error

    except Exception as e:
        logger.error(f"Error updating file statuses for agent_id {agent_id}: {e}")
        return False


async def set_custom_texts_status_to_indexing(agent_id: str, custom_texts: list[dict], status: str = "indexing") -> bool:
    """
    Update the status of custom text documents for the given agent_id and list of custom texts.
    Creates new documents for custom texts that don't exist.

    Args:
        agent_id: The ID of the agent.
        custom_texts: List of custom text dictionaries containing custom_text_alias and custom_text.
        status: The status to set (default: "indexing").

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        collection = get_collection("atlas_custom_texts")
        current_time = datetime.now(timezone.utc)

        updated_count = 0
        for item in custom_texts:
            custom_text_alias = item.get("custom_text_alias")
            if not custom_text_alias:
                logger.warning(f"custom_text_alias missing for item: {item}")
                continue

            result = await collection.update_one(
                {"agent_id": str(agent_id), "custom_text_alias": custom_text_alias},
                {
                    "$set": {"status": status, "updated_at": current_time},
                    "$setOnInsert": {
                        "agent_id": str(agent_id),
                        "custom_text_alias": custom_text_alias,
                        "created_at": current_time
                    }
                },
                upsert=True
            )
            if result.modified_count > 0 or result.upserted_id:
                updated_count += 1

        if updated_count > 0:
            logger.info(f"Updated/created {updated_count} custom text documents to '{status}' for agent_id: {agent_id}")
        else:
            logger.warning(f"No custom text documents were updated or created for agent_id: {agent_id}")
        return True

    except Exception as e:
        logger.error(f"Error updating custom text statuses for agent_id {agent_id}: {e}")
        return False


async def set_qa_pairs_status_to_indexing(agent_id: str, qa_pairs: list[dict], status: str = "indexing") -> bool:
    """
    Update the status of QA pair documents for the given agent_id and list of QA pairs.
    Creates new documents for QA pairs that don't exist.

    Args:
        agent_id: The ID of the agent.
        qa_pairs: List of QA pair dictionaries containing qna_alias, question, and answer.
        status: The status to set (default: "indexing").

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        collection = get_collection("atlas_qa_pairs")
        current_time = datetime.now(timezone.utc)

        updated_count = 0
        for item in qa_pairs:
            qna_alias = item.get("qna_alias")
            if not qna_alias:
                logger.warning(f"qna_alias missing for item: {item}")
                continue

            result = await collection.update_one(
                {"agent_id": str(agent_id), "qna_alias": qna_alias},
                {
                    "$set": {"status": status, "updated_at": current_time},
                    "$setOnInsert": {
                        "agent_id": str(agent_id),
                        "qna_alias": qna_alias,
                        "created_at": current_time
                    }
                },
                upsert=True
            )
            if result.modified_count > 0 or result.upserted_id:
                updated_count += 1

        if updated_count > 0:
            logger.info(f"Updated/created {updated_count} QA pair documents to '{status}' for agent_id: {agent_id}")
        else:
            logger.warning(f"No QA pair documents were updated or created for agent_id: {agent_id}")
        return True

    except Exception as e:
        logger.error(f"Error updating QA pair statuses for agent_id {agent_id}: {e}")
        return False


async def set_data_materials_status(requestData):
    """
    Function to set the status of all data materials (URLs, files, custom texts, QA pairs) to indexing/training based on requestData.
    """
    logger.info(f"Request data: {requestData}")

    agent_id = requestData.get("agent_id")
    if not agent_id:
        logger.error("agent_id is required in requestData")
        return False
    
    links = requestData.get("links", [])
    files = requestData.get("files", [])
    custom_texts = requestData.get("custom_texts", [])
    qa_pairs = requestData.get("qa_pairs", [])

    # Handle links
    if links:
        success = await set_url_statuses_to_indexing(agent_id, links)
        if not success:
            return False

    # Handle files
    if files:
        success = await set_file_statuses_to_indexing(agent_id, files)
        if not success:
            return False

    # Handle custom_texts
    if custom_texts:
        success = await set_custom_texts_status_to_indexing(agent_id, custom_texts)
        if not success:
            return False

    # Handle qa_pairs
    if qa_pairs:
        success = await set_qa_pairs_status_to_indexing(agent_id, qa_pairs)
        if not success:
            return False

    return True
