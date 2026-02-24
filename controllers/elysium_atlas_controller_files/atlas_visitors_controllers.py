from typing import Dict, Any, List
from logging_config import get_logger
from services.elysium_atlas_services.atlas_redis_services import get_visitor_count_for_agent

logger = get_logger()


async def get_agents_visitor_counts_controller(requestData: Dict[str, Any]) -> Dict[str, Any]:
    """
    Controller to get online visitor counts for a list of agent_ids.

    Args:
        requestData: Must contain 'agent_ids' (list of agent ID strings).

    Returns:
        Dict with visitor counts per agent.
    """
    try:
        agent_ids: List[str] = requestData.get("agent_ids", [])

        if not agent_ids:
            return {"success": False, "message": "agent_ids list is required"}

        print(f"agent_ids received: {agent_ids}")

        visitor_counts = {}
        for agent_id in agent_ids:
            count = get_visitor_count_for_agent(agent_id)
            visitor_counts[agent_id] = count if count is not None else 0

        return {"success": True, "visitor_counts": visitor_counts}

    except Exception as e:
        logger.error(f"Error in get_agents_visitor_counts_controller: {e}")
        return {"success": False, "message": str(e)}
