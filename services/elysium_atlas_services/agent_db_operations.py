from datetime import datetime, timezone
from typing import Any, Dict
from logging_config import get_logger
from services.mongo_services import get_collection
from bson import ObjectId

logger = get_logger()

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

        # Convert agent_id to ObjectId if it's a string
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
