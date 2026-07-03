import asyncio
from typing import Dict, Any
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse
from logging_config import get_logger
from config.atlas_agent_models import ListAgentsRequest
from services.elysium_atlas_services.agent_services import (
    create_agent_document,
    list_agents_for_team,
    remove_agent_by_id,
    fetch_agent_details_by_id,
    initialize_agent_update,
    initialize_agent_build_update,
    fetch_agent_fields_by_id,
    update_agent_basic_attributes,
    normalize_lead_collection_config_for_update,
    validate_user_agent_status,
    requires_agent_reindex,
    capture_pre_update_agent_status,
    normalize_agent_tool_ids_in_request,
    strip_deprecated_agent_request_fields,
)
from services.elysium_atlas_services.team_auth_services import (
    can_user_modify_agent,
    can_user_modify_team_agents,
    can_user_read_agent,
    get_agent_team_id,
    is_user_member_of_team,
    parse_session_team_context,
)
from services.elysium_atlas_services.agent_kb_services import (
    apply_agent_kb_changes,
    pop_kb_index_jobs,
    request_has_kb_payload,
)
from services.elysium_atlas_services.kb_item.kb_index_service import index_kb_item
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from services.elysium_atlas_services.agent_db_operations import check_agent_name_exists, update_agent_status
from services.elysium_atlas_services.elysium_atlas_user_plan_services import can_user_build_agent
from config.retrieval_strategy_config import normalize_retrieval_strategy_in_request
from config.llm_models_config import normalize_llm_model_in_request
from config.lead_collection_config import build_lead_collection_config_for_create
from services.elysium_atlas_services.atlas_chat_session_services import get_chat_session_data

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


def _forbidden_agent_read_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"success": False, "message": "You are not authorized to access this agent."},
    )


def _forbidden_agent_modify_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"success": False, "message": "You are not authorized to modify this agent."},
    )


def _forbidden_team_modify_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"success": False, "message": "You are not authorized to create or modify agents for this team."},
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


async def _require_agent_read(user_data: dict, agent_id: str | None) -> str | JSONResponse:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})
    if not agent_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
    if not await can_user_read_agent(user_id, agent_id):
        return _forbidden_agent_read_response()
    return str(user_id)


async def _require_agent_modify(user_data: dict, agent_id: str | None) -> str | JSONResponse:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})

    if agent_id:
        if not await can_user_modify_agent(user_id, agent_id):
            return _forbidden_agent_modify_response()
        return str(user_id)

    team_admin = await _require_team_admin(user_data)
    if isinstance(team_admin, JSONResponse):
        return team_admin
    return team_admin[0]


async def _validate_agent_tool_ids_for_request(
    request_data: dict,
    team_id: str | None,
) -> JSONResponse | None:
    if "tool_ids" not in request_data:
        return None
    if not team_id:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Cannot validate tool_ids without team context."},
        )
    error = await normalize_agent_tool_ids_in_request(request_data, team_id)
    if error:
        return JSONResponse(status_code=400, content={"success": False, "message": error})
    return None


def _schedule_kb_index_jobs(background_tasks: BackgroundTasks, request_data: dict) -> None:
    for kb_id, source_type in pop_kb_index_jobs(request_data):
        background_tasks.add_task(index_kb_item, kb_id, source_type)


async def _apply_kb_changes_for_agent(
    agent_id: str,
    team_id: str,
    user_id: str,
    request_data: dict,
    *,
    is_build: bool,
) -> tuple[list[dict] | None, JSONResponse | None]:
    if not request_has_kb_payload(request_data):
        return None, None

    attachments, error = await apply_agent_kb_changes(
        agent_id,
        team_id,
        user_id,
        request_data,
        is_build=is_build,
    )
    if error:
        return None, JSONResponse(status_code=400, content={"success": False, "message": error})
    return attachments, None


async def pre_build_agent_operations_controller(requestData: Dict[str, Any],userData: dict):
    try:
        strip_deprecated_agent_request_fields(requestData)

        team_admin = await _require_team_admin(userData)
        if isinstance(team_admin, JSONResponse):
            return team_admin

        user_id, team_id = team_admin

        plan_check = await can_user_build_agent(user_id, requestData)
        if not plan_check.get("success"):
            return JSONResponse(status_code=403, content={"success": False, "message": plan_check.get("message")})

        initial_data = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_init_config")
        
        initial_data["owner_user_id"] = user_id
        initial_data["team_id"] = team_id

        if requestData.get("agent_name") is not None:
            agent_exists = await check_agent_name_exists(user_id, requestData.get("agent_name"))
            if agent_exists:
                return JSONResponse(status_code=200, content={"success": False, "message": "An agent with this name already exists. Please choose a different name."})
            
            initial_data["agent_name"] = requestData.get("agent_name")

        retrieval_strategy_error = normalize_retrieval_strategy_in_request(requestData)
        if retrieval_strategy_error:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": retrieval_strategy_error},
            )
        if "retrieval_strategy" in requestData:
            initial_data["retrieval_strategy"] = requestData["retrieval_strategy"]

        llm_model_error = normalize_llm_model_in_request(requestData)
        if llm_model_error:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": llm_model_error},
            )
        if "llm_model" in requestData:
            initial_data["llm_model"] = requestData["llm_model"]

        lead_collection_config, lead_collection_error = build_lead_collection_config_for_create(
            requestData.get("lead_collection_config"),
        )
        if lead_collection_error:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": lead_collection_error},
            )
        initial_data["lead_collection_config"] = lead_collection_config

        tool_ids_error = await _validate_agent_tool_ids_for_request(requestData, team_id)
        if tool_ids_error:
            return tool_ids_error
        initial_data["tool_ids"] = requestData.get("tool_ids", [])

        agent_id = await create_agent_document(initial_data)
        if agent_id is None:
            return JSONResponse(status_code=500, content={"success": False, "message": "Failed to create the agent."})
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Agent created successfully.", "agent_id": agent_id})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while building the agent.", "error": str(e)})

async def build_update_agent_controller_v1(requestData,userData,background_tasks):
    try:
        strip_deprecated_agent_request_fields(requestData)

        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_modify(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        user_id = auth_result
        logger.info(f"Build/update agent requested by user_id: {user_id}")

        team_id = await get_agent_team_id(agent_id) if agent_id else None
        if not team_id:
            session_context = parse_session_team_context(userData)
            team_id = session_context[1] if session_context else None

        tool_ids_error = await _validate_agent_tool_ids_for_request(requestData, team_id)
        if tool_ids_error:
            return tool_ids_error

        if not agent_id:
            session_context = parse_session_team_context(userData)
            initial_data = {}
            if session_context:
                initial_data["owner_user_id"] = session_context[0]
                initial_data["team_id"] = session_context[1]
            agent_id = await create_agent_document(initial_data)
            requestData["agent_id"] = agent_id
            if not agent_id:
                logger.error("Failed to create agent document")
                return JSONResponse(status_code=200, content={"success": False, "message": "Failed to build the agent."})

        if not team_id:
            team_id = await get_agent_team_id(agent_id)

        if request_has_kb_payload(requestData) and not team_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Team context is required for knowledge attachments."},
            )

        kb_attachments, kb_error = await _apply_kb_changes_for_agent(
            agent_id,
            team_id,
            user_id,
            requestData,
            is_build=True,
        )
        if kb_error:
            return kb_error

        _schedule_kb_index_jobs(background_tasks, requestData)
        background_tasks.add_task(initialize_agent_build_update, requestData)

        response_content: dict[str, Any] = {
            "success": True,
            "message": "Your agent is being built.",
            "agent_id": agent_id,
        }
        if kb_attachments is not None:
            response_content["kb_attachments"] = kb_attachments

        return JSONResponse(status_code=200, content=response_content)

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while building the agent.", "error": str(e)})

async def list_agents_controller(body: ListAgentsRequest, userData: dict):
    """
    Controller to handle the logic for listing paginated agents for the user's active team.

    Returns:
        JSONResponse: A response containing the list of agents or an error message.
    """
    try:
        team_member = await _require_team_member(userData)
        if isinstance(team_member, JSONResponse):
            return team_member

        user_id, team_id = team_member
        logger.info(
            f"Listing agents for team_id: {team_id}, requested by user_id: {user_id}, "
            f"page: {body.page}, limit: {body.limit}"
        )
        result = await list_agents_for_team(team_id, page=body.page, limit=body.limit)
        return JSONResponse(status_code=200, content={"success": True, **result})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while listing agents.", "error": str(e)})

async def delete_agent_controller(requestData: dict, userData: dict):
    """
    Controller to handle the deletion of an agent by its ID.

    Args:
        agent_id: The ID of the agent to be deleted.
        userData: The user data containing the user_id.

    Returns:
        JSONResponse: A response indicating the success or failure of the operation.
    """
    try:
        agent_id = requestData.get("agent_id")
        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})

        auth_result = await _require_agent_modify(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        user_id = auth_result
        logger.info(f"Request to delete agent_id: {agent_id} by user_id: {user_id}")

        deletion_success = await remove_agent_by_id(agent_id)

        if deletion_success:
            return JSONResponse(status_code=200, content={"success": True, "message": "Agent deleted successfully."})
        else:
            return JSONResponse(status_code=404, content={"success": False, "message": "Agent not found."})

    except Exception as e:
        logger.error(f"Error in delete_agent_controller for agent_id {agent_id}: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while deleting the agent.", "error": str(e)})
    
async def get_agent_details_controller(requestData: dict, userData: dict):
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_read(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        user_id = auth_result
        logger.info(f"Request to get details for agent_id: {agent_id} by user_id: {user_id}")
        
        agent_data = await fetch_agent_details_by_id(agent_id)
        
        if not agent_data:
            return JSONResponse(status_code=404, content={"success": False, "message": "Agent not found."})
        
        return JSONResponse(status_code=200, content={"success": True, "agent_details": agent_data})
    
    except Exception as e:
        logger.error(f"Error in get_agent_details_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching agent details.", "error": str(e)})    
    
async def get_agent_fields_controller(requestData: dict):
    try:
        
        agent_id = requestData.get("agent_id")
        fields = requestData.get("fields")
        chat_session_id = requestData.get("chat_session_id")

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
        if not fields or not isinstance(fields, list):
            return JSONResponse(status_code=400, content={"success": False, "message": "fields must be a list of strings."})
        
        logger.info(f"Request to get fields {fields} for agent_id: {agent_id}.")
        
        # Run async calls in parallel
        if chat_session_id:
            agent_data, chat_session_data = await asyncio.gather(
                fetch_agent_fields_by_id(agent_id, fields),
                get_chat_session_data(requestData)
            )
        else:
            agent_data = await fetch_agent_fields_by_id(agent_id, fields)
            chat_session_data = None
        
        if agent_data is None:
            return JSONResponse(status_code=404, content={"success": False, "message": "Agent not found."})

        return JSONResponse(status_code=200, content={"success": True, "agent_fields": agent_data , "chat_session_data": chat_session_data})
    
    except Exception as e:
        logger.error(f"Error in get_agent_fields_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching agent fields.", "error": str(e)})    
    
async def update_agent_controller_v1(requestData,userData,background_tasks):
    try:
        strip_deprecated_agent_request_fields(requestData)

        agent_id = requestData.get("agent_id")
        if not agent_id:
            logger.error("agent_id is required for update operation")
            return JSONResponse(status_code=400, content={"success": False, "message": "You can't perform update without agent."})

        auth_result = await _require_agent_modify(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result
        user_id = auth_result

        team_id = await get_agent_team_id(agent_id)
        tool_ids_error = await _validate_agent_tool_ids_for_request(requestData, team_id)
        if tool_ids_error:
            return tool_ids_error

        if request_has_kb_payload(requestData) and not team_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Team context is required for knowledge attachments."},
            )

        kb_attachments, kb_error = await _apply_kb_changes_for_agent(
            agent_id,
            team_id,
            user_id,
            requestData,
            is_build=False,
        )
        if kb_error:
            return kb_error
        _schedule_kb_index_jobs(background_tasks, requestData)

        retrieval_strategy_error = normalize_retrieval_strategy_in_request(requestData)
        if retrieval_strategy_error:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": retrieval_strategy_error},
            )

        llm_model_error = normalize_llm_model_in_request(requestData)
        if llm_model_error:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": llm_model_error},
            )

        lead_collection_error = await normalize_lead_collection_config_for_update(
            agent_id,
            requestData,
        )
        if lead_collection_error:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": lead_collection_error},
            )

        agent_status_error = validate_user_agent_status(requestData)
        if agent_status_error:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": agent_status_error},
            )

        await update_agent_basic_attributes(agent_id, requestData)

        if not requires_agent_reindex(requestData):
            if "agent_status" in requestData:
                await update_agent_status(agent_id, requestData["agent_status"])

            response_content: dict[str, Any] = {
                "success": True,
                "message": "Agent updated successfully.",
                "agent_id": agent_id,
                "agent_status": requestData.get("agent_status"),
            }
            if kb_attachments is not None:
                response_content["kb_attachments"] = kb_attachments

            return JSONResponse(status_code=200, content=response_content)

        await capture_pre_update_agent_status(agent_id, requestData)
        background_tasks.add_task(initialize_agent_update, requestData)

        response_content: dict[str, Any] = {
            "success": True,
            "message": "Your agent is being updated.",
            "agent_id": agent_id,
        }
        if kb_attachments is not None:
            response_content["kb_attachments"] = kb_attachments

        return JSONResponse(status_code=200, content=response_content)

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while updating the agent.", "error": str(e)})