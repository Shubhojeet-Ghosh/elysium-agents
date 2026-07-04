from typing import Any, Dict

from fastapi.responses import JSONResponse

from logging_config import get_logger
from services.elysium_atlas_services.atlas_chat_session_services import get_agent_chat_sessions_summary
from services.elysium_atlas_services.team_auth_services import can_user_read_agent

logger = get_logger()


async def get_agent_chat_sessions_summary_controller(
    user_data: Dict[str, Any],
    agent_id: str,
) -> JSONResponse | Dict[str, Any]:
    """
    Return persisted session total and live online count for an agent.

    Intended for lightweight dashboard polling — not for full list rows.
    """
    try:
        if user_data is None or user_data.get("success") is False:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": (user_data or {}).get("message", "Unauthorized")},
            )

        user_id = user_data.get("user_id")
        if not user_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "user_id is required."},
            )
        if not agent_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "agent_id is required."},
            )
        if not await can_user_read_agent(str(user_id), agent_id):
            return JSONResponse(
                status_code=403,
                content={"success": False, "message": "You are not authorized to access this agent."},
            )

        summary = await get_agent_chat_sessions_summary(agent_id)
        if summary is None:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Failed to fetch chat sessions summary."},
            )

        logger.info(
            f"Chat sessions summary for agent_id={agent_id}: "
            f"total={summary['total']} online_count={summary['online_count']}"
        )
        return {"success": True, **summary}

    except Exception as e:
        logger.error(f"Error in get_agent_chat_sessions_summary_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Internal server error"},
        )
