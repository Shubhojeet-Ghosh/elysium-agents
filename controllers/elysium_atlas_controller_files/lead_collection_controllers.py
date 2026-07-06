from fastapi.responses import JSONResponse

from config.lead_collection_models import (
    GetLeadCollectionConfigRequest,
    ResetLeadCollectionConfigRequest,
    UpdateLeadCollectionConfigRequest,
    UpdateSessionLeadRequest,
    build_partial_lead_collection_config_from_request,
)
from logging_config import get_logger
from services.elysium_atlas_services.lead_collection_config_services import (
    get_lead_collection_config_for_agent,
    get_lead_collection_field_catalog,
    reset_lead_collection_config_for_agent,
    update_lead_collection_config_for_agent,
)
from services.elysium_atlas_services.team_auth_services import (
    can_user_modify_agent,
    can_user_read_agent,
)

logger = get_logger()


def _unauthenticated_response(user_data: dict | None) -> JSONResponse | None:
    if user_data is None or user_data.get("success") is False:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": (user_data or {}).get("message", "Unauthorized")},
        )
    return None


async def _require_agent_read(user_data: dict, agent_id: str) -> JSONResponse | None:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})

    if not await can_user_read_agent(str(user_id), agent_id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "You are not authorized to access this agent."},
        )
    return None


async def _require_agent_modify(user_data: dict, agent_id: str) -> JSONResponse | None:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})

    if not await can_user_modify_agent(str(user_id), agent_id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "You are not authorized to modify this agent."},
        )
    return None


async def _require_session_lead_edit(
    user_data: dict,
    agent_id: str,
    chat_session_id: str,
) -> JSONResponse | None:
    """
    Owner/admin: may edit leads for any session on the agent.
    Member: may edit only when they are the active takeover handler (in_conversation_with).
    """
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})

    user_id_str = str(user_id)
    if not await can_user_read_agent(user_id_str, agent_id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "You are not authorized to access this agent."},
        )

    if await can_user_modify_agent(user_id_str, agent_id):
        return None

    from services.elysium_atlas_services.atlas_chat_session_services import (
        get_chat_session_in_conversation_with,
    )

    handler_id = await get_chat_session_in_conversation_with(agent_id, chat_session_id)
    if handler_id and handler_id == user_id_str:
        return None

    return JSONResponse(
        status_code=403,
        content={
            "success": False,
            "message": (
                "You can only edit contact details while you're handling this conversation. "
                "Take over the chat first."
            ),
        },
    )


async def get_lead_collection_config_controller(
    body: GetLeadCollectionConfigRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        auth_error = await _require_agent_read(user_data, body.agent_id)
        if auth_error:
            return auth_error

        config = await get_lead_collection_config_for_agent(body.agent_id)
        if config is None:
            return JSONResponse(status_code=404, content={"success": False, "message": "Agent not found."})

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "agent_id": body.agent_id,
                "lead_collection_config": config,
                "field_catalog": get_lead_collection_field_catalog(),
            },
        )
    except Exception as e:
        logger.error(
            "Error in get_lead_collection_config_controller for agent_id=%s: %s",
            body.agent_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching lead collection config."},
        )


async def update_lead_collection_config_controller(
    body: UpdateLeadCollectionConfigRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        auth_error = await _require_agent_modify(user_data, body.agent_id)
        if auth_error:
            return auth_error

        partial = build_partial_lead_collection_config_from_request(body)
        if not partial:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "At least one lead collection field must be provided.",
                },
            )

        merged, error_message = await update_lead_collection_config_for_agent(body.agent_id, partial)
        if error_message:
            status_code = 404 if error_message == "Agent not found." else 400
            return JSONResponse(
                status_code=status_code,
                content={"success": False, "message": error_message},
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Lead collection config updated successfully.",
                "agent_id": body.agent_id,
                "lead_collection_config": merged,
            },
        )
    except Exception as e:
        logger.error(
            "Error in update_lead_collection_config_controller for agent_id=%s: %s",
            body.agent_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while updating lead collection config."},
        )


async def reset_lead_collection_config_controller(
    body: ResetLeadCollectionConfigRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        auth_error = await _require_agent_modify(user_data, body.agent_id)
        if auth_error:
            return auth_error

        default_config, error_message = await reset_lead_collection_config_for_agent(body.agent_id)
        if error_message:
            status_code = 404 if error_message == "Agent not found." else 400
            return JSONResponse(
                status_code=status_code,
                content={"success": False, "message": error_message},
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Lead collection config reset to defaults.",
                "agent_id": body.agent_id,
                "lead_collection_config": default_config,
            },
        )
    except Exception as e:
        logger.error(
            "Error in reset_lead_collection_config_controller for agent_id=%s: %s",
            body.agent_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while resetting lead collection config."},
        )


async def update_session_lead_controller(
    body: UpdateSessionLeadRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        auth_error = await _require_session_lead_edit(user_data, body.agent_id, body.chat_session_id)
        if auth_error:
            return auth_error

        from services.elysium_atlas_services.agent_db_operations import get_agent_by_id
        from services.elysium_atlas_services.lead_collection_services import (
            ERR_SESSION_NOT_FOUND,
            map_session_lead_update_error,
            update_session_lead_by_team_member,
        )

        agent_data = await get_agent_by_id(body.agent_id)
        if not agent_data:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "This agent couldn't be found."},
            )

        payload, error_code = await update_session_lead_by_team_member(
            agent_id=body.agent_id,
            chat_session_id=body.chat_session_id,
            field_updates=dict(body.fields),
            agent_data=agent_data,
        )
        if error_code:
            status_code = 404 if error_code == ERR_SESSION_NOT_FOUND else 400
            return JSONResponse(
                status_code=status_code,
                content={"success": False, "message": map_session_lead_update_error(error_code)},
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                **payload,
            },
        )
    except Exception as e:
        logger.error(
            "Error in update_session_lead_controller agent_id=%s chat_session_id=%s: %s",
            body.agent_id,
            body.chat_session_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Something went wrong while saving contact details. Please try again.",
            },
        )


async def get_lead_collection_field_catalog_controller(user_data: dict) -> JSONResponse:
    try:
        auth_error = _unauthenticated_response(user_data)
        if auth_error:
            return auth_error

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "field_catalog": get_lead_collection_field_catalog(),
            },
        )
    except Exception as e:
        logger.error("Error in get_lead_collection_field_catalog_controller: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching lead field catalog."},
        )
