from fastapi.responses import JSONResponse

from config.atlas_dashboard_models import ChatSessionCountsRequest
from logging_config import get_logger
from services.elysium_atlas_services.atlas_dashboard_services import get_chat_session_counts
from services.elysium_atlas_services.team_auth_services import (
    get_agent_team_id,
    is_user_member_of_team,
    parse_session_team_context,
)

logger = get_logger()


def _unauthenticated_response(user_data: dict | None) -> JSONResponse | None:
    if user_data is None or user_data.get("success") is False:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": (user_data or {}).get("message", "Unauthorized")},
        )
    return None


async def _require_team_member(user_data: dict) -> tuple[str, str] | JSONResponse:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    session_context = parse_session_team_context(user_data)
    if session_context is None:
        if not user_data.get("user_id"):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "user_id is required."},
            )
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "No team context. Select a team to continue."},
        )

    user_id, team_id = session_context
    if not await is_user_member_of_team(user_id, team_id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "You are not a member of this team."},
        )
    return user_id, team_id


async def get_chat_session_counts_controller(
    body: ChatSessionCountsRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        team_member = await _require_team_member(user_data)
        if isinstance(team_member, JSONResponse):
            return team_member

        user_id, team_id = team_member

        if body.agent_id:
            agent_team_id = await get_agent_team_id(body.agent_id)
            if not agent_team_id:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "message": "Agent not found."},
                )
            if agent_team_id != team_id:
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "message": "You are not authorized to access this agent.",
                    },
                )

        result = await get_chat_session_counts(
            team_id,
            body.range,
            agent_id=body.agent_id,
        )
        logger.info(
            "Chat session counts user_id=%s team_id=%s agent_id=%s range=%s "
            "total=%s total_visitor_messages=%s",
            user_id,
            team_id,
            body.agent_id,
            body.range,
            result.get("total"),
            result.get("total_visitor_messages"),
        )
        return JSONResponse(status_code=200, content={"success": True, **result})
    except Exception as e:
        logger.error(
            "Error in get_chat_session_counts_controller team_id=%s agent_id=%s range=%s: %s",
            (user_data or {}).get("team_id"),
            body.agent_id,
            body.range,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching chat session counts."},
        )
