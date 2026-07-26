from fastapi.responses import JSONResponse

from config.human_handover_models import (
    GetHumanHandoverConfigRequest,
    ResetHumanHandoverConfigRequest,
    UpdateHumanHandoverConfigRequest,
    VisitorHandoverContactDeclineRequest,
    VisitorHandoverContactRequest,
    build_partial_human_handover_config_from_request,
)
from logging_config import get_logger
from services.elysium_atlas_services.human_handover_config_services import (
    get_human_handover_config_for_agent,
    reset_human_handover_config_for_agent,
    update_human_handover_config_for_agent,
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


async def get_human_handover_config_controller(
    body: GetHumanHandoverConfigRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        auth_error = await _require_agent_read(user_data, body.agent_id)
        if auth_error:
            return auth_error

        config = await get_human_handover_config_for_agent(body.agent_id)
        if config is None:
            return JSONResponse(status_code=404, content={"success": False, "message": "Agent not found."})

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "agent_id": body.agent_id,
                "human_handover_config": config,
            },
        )
    except Exception as e:
        logger.error(
            "Error in get_human_handover_config_controller for agent_id=%s: %s",
            body.agent_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching human handover config."},
        )


async def update_human_handover_config_controller(
    body: UpdateHumanHandoverConfigRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        auth_error = await _require_agent_modify(user_data, body.agent_id)
        if auth_error:
            return auth_error

        partial = build_partial_human_handover_config_from_request(body)
        if not partial:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "At least one human handover field must be provided.",
                },
            )

        merged, error_message = await update_human_handover_config_for_agent(body.agent_id, partial)
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
                "message": "Human handover config updated successfully.",
                "agent_id": body.agent_id,
                "human_handover_config": merged,
            },
        )
    except Exception as e:
        logger.error(
            "Error in update_human_handover_config_controller for agent_id=%s: %s",
            body.agent_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while updating human handover config."},
        )


async def reset_human_handover_config_controller(
    body: ResetHumanHandoverConfigRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        auth_error = await _require_agent_modify(user_data, body.agent_id)
        if auth_error:
            return auth_error

        default_config, error_message = await reset_human_handover_config_for_agent(body.agent_id)
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
                "message": "Human handover config reset to defaults.",
                "agent_id": body.agent_id,
                "human_handover_config": default_config,
            },
        )
    except Exception as e:
        logger.error(
            "Error in reset_human_handover_config_controller for agent_id=%s: %s",
            body.agent_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while resetting human handover config."},
        )


async def visitor_handover_contact_controller(body: VisitorHandoverContactRequest) -> JSONResponse:
    try:
        from services.elysium_atlas_services.human_handover_services import (
            map_handover_contact_error,
            submit_handover_contact,
        )

        payload, error_code = await submit_handover_contact(
            agent_id=body.agent_id,
            chat_session_id=body.chat_session_id,
            name=body.name,
            email=body.email,
        )
        if error_code:
            status_code = 404 if error_code == "SESSION_NOT_FOUND" else 400
            return JSONResponse(
                status_code=status_code,
                content={"success": False, "message": map_handover_contact_error(error_code)},
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Contact details saved.",
                **payload,
            },
        )
    except Exception as e:
        logger.error(
            "Error in visitor_handover_contact_controller agent_id=%s chat_session_id=%s: %s",
            body.agent_id,
            body.chat_session_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while saving contact details."},
        )


async def visitor_handover_contact_decline_controller(
    body: VisitorHandoverContactDeclineRequest,
) -> JSONResponse:
    try:
        from services.elysium_atlas_services.human_handover_services import (
            decline_handover_contact,
            map_handover_contact_error,
        )

        payload, error_code = await decline_handover_contact(
            agent_id=body.agent_id,
            chat_session_id=body.chat_session_id,
        )
        if error_code:
            status_code = 404 if error_code == "SESSION_NOT_FOUND" else 400
            return JSONResponse(
                status_code=status_code,
                content={"success": False, "message": map_handover_contact_error(error_code)},
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Contact form declined.",
                **payload,
            },
        )
    except Exception as e:
        logger.error(
            "Error in visitor_handover_contact_decline_controller agent_id=%s chat_session_id=%s: %s",
            body.agent_id,
            body.chat_session_id,
            e,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while declining the contact form."},
        )
