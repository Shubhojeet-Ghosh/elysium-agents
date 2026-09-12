import json

from fastapi.responses import JSONResponse

from config.atlas_plugin_models import (
    CreatePluginRequest,
    DeletePluginRequest,
    GetPluginRequest,
    ListPluginsRequest,
    SetPluginSecretsRequest,
    TestPluginRequest,
    UpdatePluginRequest,
)
from logging_config import get_logger
from services.elysium_atlas_services.atlas_plugin_execution_services import execute_atlas_plugin
from services.elysium_atlas_services.atlas_plugin_services import (
    create_plugin,
    delete_plugin,
    get_plugin_by_id,
    get_plugin_document_by_id,
    get_plugin_team_id,
    list_plugins_for_team,
    set_plugin_secrets,
    update_plugin,
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
        content={"success": False, "message": "You are not authorized to create or modify plugins for this team."},
    )


def _forbidden_plugin_read_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"success": False, "message": "You are not authorized to access this plugin."},
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


async def _require_plugin_read(user_data: dict, plugin_id: str) -> JSONResponse | None:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})

    plugin_team_id = await get_plugin_team_id(plugin_id)
    if not plugin_team_id:
        return JSONResponse(status_code=404, content={"success": False, "message": "Plugin not found."})
    if not await is_user_member_of_team(str(user_id), plugin_team_id):
        return _forbidden_plugin_read_response()
    return None


async def _require_plugin_modify(user_data: dict, plugin_id: str) -> JSONResponse | None:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})

    plugin_team_id = await get_plugin_team_id(plugin_id)
    if not plugin_team_id:
        return JSONResponse(status_code=404, content={"success": False, "message": "Plugin not found."})
    if not await can_user_modify_team_agents(str(user_id), plugin_team_id):
        return _forbidden_team_modify_response()
    return None


def _failure_response(result: dict) -> JSONResponse:
    status_code = result.get("status_code", 400)
    return JSONResponse(status_code=status_code, content={"success": False, "message": result["message"]})


async def create_plugin_controller(body: CreatePluginRequest, user_data: dict) -> JSONResponse:
    try:
        team_admin = await _require_team_admin(user_data)
        if isinstance(team_admin, JSONResponse):
            return team_admin

        user_id, team_id = team_admin
        result = await create_plugin(team_id, user_id, body)
        if not result.get("success"):
            return _failure_response(result)

        return JSONResponse(status_code=200, content={"success": True, "plugin": result["plugin"]})
    except Exception as e:
        logger.error(f"Error in create_plugin_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while creating the plugin."},
        )


async def list_plugins_controller(body: ListPluginsRequest, user_data: dict) -> JSONResponse:
    try:
        team_member = await _require_team_member(user_data)
        if isinstance(team_member, JSONResponse):
            return team_member

        _, team_id = team_member
        result = await list_plugins_for_team(
            team_id=team_id,
            page=body.page,
            limit=body.limit,
            include_inactive=body.include_inactive,
        )
        return JSONResponse(status_code=200, content=result)
    except Exception as e:
        logger.error(f"Error in list_plugins_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while listing plugins."},
        )


async def get_plugin_controller(body: GetPluginRequest, user_data: dict) -> JSONResponse:
    try:
        auth_error = await _require_plugin_read(user_data, body.plugin_id)
        if auth_error:
            return auth_error

        plugin = await get_plugin_by_id(body.plugin_id)
        if not plugin:
            return JSONResponse(status_code=404, content={"success": False, "message": "Plugin not found."})

        return JSONResponse(status_code=200, content={"success": True, "plugin": plugin})
    except Exception as e:
        logger.error(f"Error in get_plugin_controller for plugin_id={body.plugin_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching the plugin."},
        )


async def update_plugin_controller(body: UpdatePluginRequest, user_data: dict) -> JSONResponse:
    try:
        auth_error = await _require_plugin_modify(user_data, body.plugin_id)
        if auth_error:
            return auth_error

        result = await update_plugin(body.plugin_id, body)
        if not result.get("success"):
            return _failure_response(result)

        return JSONResponse(status_code=200, content={"success": True, "plugin": result["plugin"]})
    except Exception as e:
        logger.error(f"Error in update_plugin_controller for plugin_id={body.plugin_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while updating the plugin."},
        )


async def delete_plugin_controller(body: DeletePluginRequest, user_data: dict) -> JSONResponse:
    try:
        auth_error = await _require_plugin_modify(user_data, body.plugin_id)
        if auth_error:
            return auth_error

        result = await delete_plugin(body.plugin_id)
        if not result.get("success"):
            return _failure_response(result)

        return JSONResponse(status_code=200, content={"success": True, "message": result["message"]})
    except Exception as e:
        logger.error(f"Error in delete_plugin_controller for plugin_id={body.plugin_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while deleting the plugin."},
        )


async def set_plugin_secrets_controller(body: SetPluginSecretsRequest, user_data: dict) -> JSONResponse:
    try:
        auth_error = await _require_plugin_modify(user_data, body.plugin_id)
        if auth_error:
            return auth_error

        result = await set_plugin_secrets(body.plugin_id, body)
        if not result.get("success"):
            return _failure_response(result)

        return JSONResponse(status_code=200, content={"success": True, "plugin": result["plugin"]})
    except Exception as e:
        logger.error(
            f"Error in set_plugin_secrets_controller for plugin_id={body.plugin_id}: {e}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while saving plugin secrets."},
        )


async def test_plugin_controller(body: TestPluginRequest, user_data: dict) -> JSONResponse:
    try:
        auth_error = await _require_plugin_modify(user_data, body.plugin_id)
        if auth_error:
            return auth_error

        document = await get_plugin_document_by_id(body.plugin_id)
        if not document:
            return JSONResponse(status_code=404, content={"success": False, "message": "Plugin not found."})

        raw_result = await execute_atlas_plugin(document, body.inputs)
        try:
            parsed = json.loads(raw_result)
        except (json.JSONDecodeError, TypeError):
            parsed = raw_result

        is_error = isinstance(parsed, dict) and parsed.get("error") is True
        return JSONResponse(
            status_code=200,
            content={
                "success": not is_error,
                "result": parsed,
            },
        )
    except Exception as e:
        logger.error(f"Error in test_plugin_controller for plugin_id={body.plugin_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while testing the plugin."},
        )
