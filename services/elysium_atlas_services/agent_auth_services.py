from datetime import datetime, timezone
from typing import Any, Dict
from logging_config import get_logger
from services.mongo_services import get_collection
from bson import ObjectId

logger = get_logger()


async def is_user_owner_of_agent(user_id: str, agent_id: str) -> bool:
    """
    Check if the given user_id is the owner of the specified agent_id.

    Args:
        user_id: The ID of the user to check.
        agent_id: The ID of the agent to check.

    Returns:
        bool: True if the user_id is the owner of the agent_id, False otherwise.
    """
    try:
        collection = get_collection("atlas_agents")

        # Convert agent_id to ObjectId
        agent_object_id = ObjectId(agent_id)

        # Query to find the agent with the given agent_id and owner_user_id
        agent = await collection.find_one({"_id": agent_object_id, "owner_user_id": user_id})

        if agent:
            logger.info(f"User {user_id} is the owner of agent {agent_id}.")
            return True
        else:
            logger.info(f"User {user_id} is not the owner of agent {agent_id}.")
            return False

    except Exception as e:
        logger.error(f"Error checking ownership for user_id {user_id} and agent_id {agent_id}: {e}")
        return False