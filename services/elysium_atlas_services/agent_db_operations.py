from datetime import datetime, timezone
from typing import Any, Dict
from logging_config import get_logger
from services.mongo_services import get_collection
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

    # TODO: Handle custom_texts, qa_pairs similarly

    return True
