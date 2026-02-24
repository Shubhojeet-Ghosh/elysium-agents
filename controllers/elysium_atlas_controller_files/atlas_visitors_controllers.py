from typing import Dict, Any, List
from fastapi.responses import JSONResponse

from logging_config import get_logger
from services.elysium_atlas_services.atlas_redis_services import get_visitor_count_for_agent
from services.elysium_atlas_services.agent_db_operations import get_agent_ids_by_owner_user_id

logger = get_logger()


async def get_agents_visitor_counts_controller(userData: Dict[str, Any]) -> Dict[str, Any]:
    """
    Controller to get online visitor counts for a list of agent_ids.

    Args:
        userData: Must contain 'user_id' (string).

    Returns:
        Dict with visitor counts per agent.
    """
    try:

        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        logger.info(f"User data: {userData}")

        user_id = userData.get("user_id")

        agent_ids: List[str] = await get_agent_ids_by_owner_user_id(user_id)

        if not agent_ids:
            return {"success": True, "visitor_counts": {}}

        logger.info(f"agent_ids for user_id {user_id}: {agent_ids}")
    
        visitor_counts = {}
        for agent_id in agent_ids:
            count = get_visitor_count_for_agent(agent_id)
            visitor_counts[agent_id] = count if count is not None else 0

        return {"success": True, "visitor_counts": visitor_counts}

    except Exception as e:
        logger.error(f"Error in get_agents_visitor_counts_controller: {e}")
        return {"success": False, "message": str(e)}
