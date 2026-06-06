from fastapi.responses import JSONResponse

from config.email_user_models import ListTeamUsersRequest
from logging_config import get_logger
from services.email_agent_services.email_team_users_services import list_team_users

logger = get_logger()


async def list_team_users_controller(request_data: ListTeamUsersRequest):
    try:
        result = await list_team_users(team_id=request_data.team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch team users."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "users": result["data"]["users"],
            },
        )

    except Exception as e:
        logger.error(f"Error in list_team_users_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching team users.",
            },
        )
