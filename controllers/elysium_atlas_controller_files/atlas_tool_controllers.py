from fastapi.responses import JSONResponse

from config.atlas_tool_models import (
    CreateToolRequest,
    DeleteToolRequest,
    GetToolRequest,
    ListToolsRequest,
    UpdateToolRequest,
)
from logging_config import get_logger
from services.elysium_atlas_services.atlas_tool_services import (
    create_tool,
    delete_tool,
    get_tool_by_id,
    get_tool_team_id,
    list_tools_for_team,
    update_tool,
)
from services.elysium_atlas_services.team_auth_services import (
    can_user_modify_team_agents,
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


def _no_team_context_response(user_data: dict) -> JSONResponse:
    if not user_data.get("user_id"):
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})
    return JSONResponse(
        status_code=403,
        content={"success": False, "message": "No team context. Select a team to continue."},
    )


def _forbidden_team_modify_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"success": False, "message": "You are not authorized to create or modify tools for this team."},
    )


def _forbidden_tool_read_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"success": False, "message": "You are not authorized to access this tool."},
    )


async def _require_team_member(user_data: dict) -> tuple[str, str] | JSONResponse:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    session_context = parse_session_team_context(user_data)
    if session_context is None:
        return _no_team_context_response(user_data)

    user_id, team_id = session_context
    if not await is_user_member_of_team(user_id, team_id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "You are not a member of this team."},
        )
    return user_id, team_id


async def _require_team_admin(user_data: dict) -> tuple[str, str] | JSONResponse:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    session_context = parse_session_team_context(user_data)
    if session_context is None:
        return _no_team_context_response(user_data)

    user_id, team_id = session_context
    if not await can_user_modify_team_agents(user_id, team_id):
        return _forbidden_team_modify_response()
    return user_id, team_id


async def _require_tool_read(user_data: dict, tool_id: str) -> JSONResponse | None:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})

    tool_team_id = await get_tool_team_id(tool_id)
    if not tool_team_id:
        return JSONResponse(status_code=404, content={"success": False, "message": "Tool not found."})
    if not await is_user_member_of_team(str(user_id), tool_team_id):
        return _forbidden_tool_read_response()
    return None


async def _require_tool_modify(user_data: dict, tool_id: str) -> JSONResponse | None:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})

    tool_team_id = await get_tool_team_id(tool_id)
    if not tool_team_id:
        return JSONResponse(status_code=404, content={"success": False, "message": "Tool not found."})
    if not await can_user_modify_team_agents(str(user_id), tool_team_id):
        return _forbidden_team_modify_response()
    return None


async def create_tool_controller(body: CreateToolRequest, user_data: dict) -> JSONResponse:
    try:
        team_admin = await _require_team_admin(user_data)
        if isinstance(team_admin, JSONResponse):
            return team_admin

        user_id, team_id = team_admin
        result = await create_tool(team_id, user_id, body)
        if not result.get("success"):
            return JSONResponse(status_code=409, content={"success": False, "message": result["message"]})

        return JSONResponse(status_code=200, content={"success": True, "tool": result["tool"]})
    except Exception as e:
        logger.error(f"Error in create_tool_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while creating the tool."},
        )


async def list_tools_controller(body: ListToolsRequest, user_data: dict) -> JSONResponse:
    try:
        team_member = await _require_team_member(user_data)
        if isinstance(team_member, JSONResponse):
            return team_member

        _, team_id = team_member
        result = await list_tools_for_team(
            team_id=team_id,
            page=body.page,
            limit=body.limit,
            include_inactive=body.include_inactive,
        )
        return JSONResponse(status_code=200, content=result)
    except Exception as e:
        logger.error(f"Error in list_tools_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while listing tools."},
        )


async def get_tool_controller(body: GetToolRequest, user_data: dict) -> JSONResponse:
    try:
        auth_error = await _require_tool_read(user_data, body.tool_id)
        if auth_error:
            return auth_error

        tool = await get_tool_by_id(body.tool_id)
        if not tool:
            return JSONResponse(status_code=404, content={"success": False, "message": "Tool not found."})

        return JSONResponse(status_code=200, content={"success": True, "tool": tool})
    except Exception as e:
        logger.error(f"Error in get_tool_controller for tool_id={body.tool_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching the tool."},
        )


async def update_tool_controller(body: UpdateToolRequest, user_data: dict) -> JSONResponse:
    try:
        auth_error = await _require_tool_modify(user_data, body.tool_id)
        if auth_error:
            return auth_error

        result = await update_tool(body.tool_id, body)
        if not result.get("success"):
            status_code = result.get("status_code", 400)
            return JSONResponse(status_code=status_code, content={"success": False, "message": result["message"]})

        return JSONResponse(status_code=200, content={"success": True, "tool": result["tool"]})
    except Exception as e:
        logger.error(f"Error in update_tool_controller for tool_id={body.tool_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while updating the tool."},
        )


async def delete_tool_controller(body: DeleteToolRequest, user_data: dict) -> JSONResponse:
    try:
        auth_error = await _require_tool_modify(user_data, body.tool_id)
        if auth_error:
            return auth_error

        result = await delete_tool(body.tool_id)
        if not result.get("success"):
            status_code = result.get("status_code", 400)
            return JSONResponse(status_code=status_code, content={"success": False, "message": result["message"]})

        return JSONResponse(status_code=200, content={"success": True, "message": result["message"]})
    except Exception as e:
        logger.error(f"Error in delete_tool_controller for tool_id={body.tool_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while deleting the tool."},
        )
