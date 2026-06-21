import asyncio
from typing import Dict, Any
from fastapi.responses import JSONResponse
from logging_config import get_logger
from config.atlas_agent_models import ListAgentsRequest
from services.elysium_atlas_services.agent_services import initialize_agent_build_update, create_agent_document, list_agents_for_team, remove_agent_by_id,fetch_agent_details_by_id,initialize_agent_update, fetch_agent_fields_by_id, fetch_agent_urls, fetch_agent_files, fetch_agent_custom_texts, fetch_agent_qa_pairs, remove_agent_links, remove_agent_files, update_agent_basic_attributes, normalize_lead_collection_config_for_update, validate_user_agent_status, requires_agent_reindex, capture_pre_update_agent_status, normalize_agent_tool_ids_in_request
from services.elysium_atlas_services.atlas_custom_knowledge_services import remove_custom_data, get_custom_text_from_qdrant, get_qa_pair_from_qdrant
from services.elysium_atlas_services.team_auth_services import (
    can_user_modify_agent,
    can_user_modify_team_agents,
    can_user_read_agent,
    get_agent_team_id,
    is_user_member_of_team,
    parse_session_team_context,
)
from services.elysium_atlas_services.atlas_chat_session_services import get_chat_session_data
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from config.elysium_atlas_s3_config import ELYSIUM_ATLAS_BUCKET_NAME, ELYSIUM_CDN_BASE_URL, ELYSIUM_GLOBAL_BUCKET_NAME
from services.aws_services.s3_service import generate_presigned_upload_url
from services.elysium_atlas_services.agent_db_operations import check_agent_name_exists, update_agent_fields
from services.elysium_atlas_services.agent_db_operations import update_agent_status
from services.elysium_atlas_services.agent_db_operations import set_data_materials_status
from services.elysium_atlas_services.elysium_atlas_user_plan_services import can_user_build_agent
from config.retrieval_strategy_config import normalize_retrieval_strategy_in_request
from config.llm_models_config import normalize_llm_model_in_request
from config.lead_collection_config import build_lead_collection_config_for_create

logger = get_logger()


def _datasource_list_response(message: str, items_key: str, result: dict) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": message,
            items_key: result["data"],
            "total": result["total"],
            "page": result["page"],
            "limit": result["limit"],
            "total_pages": result["total_pages"],
            "has_next": result["has_next"],
            "has_prev": result["has_prev"],
        },
    )


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


async def pre_build_agent_operations_controller(requestData: Dict[str, Any],userData: dict):
    try:
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
        
        # Set agent status to 'indexing' after creation/update
        await update_agent_status(agent_id, "indexing")

        # logger.info(f"buil/update agent with request data: {requestData}")
        
        # Store links in MongoDB
        background_tasks.add_task(initialize_agent_build_update,requestData)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Your agent is being build.", "agent_id": requestData.get("agent_id")})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while building the agent.", "error": str(e)})

async def generate_presigned_url_controller(requestData,userData):
    try:
        team_admin = await _require_team_admin(userData)
        if isinstance(team_admin, JSONResponse):
            return team_admin

        user_id, _team_id = team_admin
        logger.info(f"Generating presigned URLs for user_id: {user_id}")
        
        presigned_urls = dict[Any, Any]()

        files = requestData.get("files")
        presigned_urls_for_files = []
        if files:
            for file in files:
                folder_path = file.get("folder_path")
                filename = file.get("filename")
                filetype = file.get("filetype")
                visibility = file.get("visibility","private")
                
                # Use ELYSIUM_GLOBAL_BUCKET_NAME if visibility is "public", otherwise use ELYSIUM_ATLAS_BUCKET_NAME
                bucket_name = ELYSIUM_GLOBAL_BUCKET_NAME if visibility == "public" else ELYSIUM_ATLAS_BUCKET_NAME
                
                # Add "elysium-atlas/" prefix to folder_path if visibility is "public"
                if visibility == "public":
                    folder_path = f"elysium-atlas/{folder_path}" if folder_path else "elysium-atlas"
                
                presigned_url = generate_presigned_upload_url(bucket_name, folder_path, filename, filetype, visibility=visibility)
                if presigned_url:
                    presigned_urls_for_files.append(presigned_url)
        
        presigned_urls["files"] = presigned_urls_for_files

        return JSONResponse(status_code=200, content={"success": True, "message": "Presigned urls generated", "presigned_urls": presigned_urls})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while generating presigned urls.", "error": str(e)})

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
        agent_id = requestData.get("agent_id")
        if not agent_id:
            logger.error("agent_id is required for update operation")
            return JSONResponse(status_code=400, content={"success": False, "message": "You can't perform update without agent."})

        auth_result = await _require_agent_modify(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        team_id = await get_agent_team_id(agent_id)
        tool_ids_error = await _validate_agent_tool_ids_for_request(requestData, team_id)
        if tool_ids_error:
            return tool_ids_error

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

            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Agent updated successfully.",
                    "agent_id": agent_id,
                    "agent_status": requestData.get("agent_status"),
                },
            )

        await capture_pre_update_agent_status(agent_id, requestData)

        await set_data_materials_status(requestData)
        await update_agent_status(agent_id, "updating")
        background_tasks.add_task(initialize_agent_update, requestData)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Your agent is being updated.", "agent_id": requestData.get("agent_id")})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while updating the agent.", "error": str(e)})

async def get_agent_urls_controller(requestData: dict, userData: dict):
    """
    Controller to fetch paginated URLs for an agent.
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_read(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        page = requestData.get("page", 1)
        limit = requestData.get("limit", 10)

        logger.info(f"Fetching URLs for agent_id: {agent_id}, page: {page}, limit: {limit}")

        result = await fetch_agent_urls(agent_id, page=page, limit=limit)

        return _datasource_list_response("URLs fetched successfully.", "urls", result)
    
    except Exception as e:
        logger.error(f"Error in get_agent_urls_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching URLs.", "error": str(e)})

async def get_agent_files_controller(requestData: dict, userData: dict):
    """
    Controller to fetch paginated files for an agent.
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_read(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        page = requestData.get("page", 1)
        limit = requestData.get("limit", 10)

        logger.info(f"Fetching files for agent_id: {agent_id}, page: {page}, limit: {limit}")

        result = await fetch_agent_files(agent_id, page=page, limit=limit)

        return _datasource_list_response("Files fetched successfully.", "files", result)
    
    except Exception as e:
        logger.error(f"Error in get_agent_files_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching files.", "error": str(e)})

async def get_agent_custom_texts_controller(requestData: dict, userData: dict):
    """
    Controller to fetch paginated custom texts for an agent.
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_read(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        page = requestData.get("page", 1)
        limit = requestData.get("limit", 10)

        logger.info(f"Fetching custom texts for agent_id: {agent_id}, page: {page}, limit: {limit}")

        result = await fetch_agent_custom_texts(agent_id, page=page, limit=limit)

        return _datasource_list_response("Custom texts fetched successfully.", "custom_texts", result)
    
    except Exception as e:
        logger.error(f"Error in get_agent_custom_texts_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching custom texts.", "error": str(e)})

async def get_agent_qa_pairs_controller(requestData: dict, userData: dict):
    """
    Controller to fetch paginated QA pairs for an agent.
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_read(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        page = requestData.get("page", 1)
        limit = requestData.get("limit", 10)

        logger.info(f"Fetching QA pairs for agent_id: {agent_id}, page: {page}, limit: {limit}")

        result = await fetch_agent_qa_pairs(agent_id, page=page, limit=limit)

        return _datasource_list_response("QA pairs fetched successfully.", "qa_pairs", result)
    
    except Exception as e:
        logger.error(f"Error in get_agent_qa_pairs_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching QA pairs.", "error": str(e)})

async def remove_agent_links_controller(requestData: dict, userData: dict):
    """
    Controller to remove specific links from an agent (MongoDB and Qdrant).
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_modify(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        user_id = auth_result
        links = requestData.get("links")

        if not links or not isinstance(links, list) or len(links) == 0:
            return JSONResponse(status_code=400, content={"success": False, "message": "links must be a non-empty list."})
        
        logger.info(f"Removing {len(links)} links for agent_id: {agent_id} by user_id: {user_id}")
        
        result = await remove_agent_links(agent_id, links)
        
        if result.get("success"):
            return JSONResponse(status_code=200, content={
                "success": True,
                "message": f"Successfully removed links from agent.",
                "errors": result.get("errors", [])
            })
        else:
            return JSONResponse(status_code=500, content={
                "success": False,
                "message": "Failed to remove links.",
                "errors": result.get("errors", [])
            })
    
    except Exception as e:
        logger.error(f"Error in remove_agent_links_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while removing links.", "error": str(e)})

async def delete_agent_files_controller(requestData: dict, userData: dict):
    """
    Controller to delete specific files from an agent.
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_modify(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        user_id = auth_result
        files = requestData.get("files")

        if not files or not isinstance(files, list) or len(files) == 0:
            return JSONResponse(status_code=400, content={"success": False, "message": "files must be a non-empty list."})
        
        logger.info(f"Deleting {len(files)} files for agent_id: {agent_id} by user_id: {user_id}")
        
        result = await remove_agent_files(agent_id, files)
        
        if result.get("success"):
            return JSONResponse(status_code=200, content={"success": True, "message": "Files deleted successfully."})
        else:
            return JSONResponse(status_code=500, content={"success": False, "message": "Failed to delete files.", "errors": result.get("errors", [])})
    
    except Exception as e:
        logger.error(f"Error in delete_agent_files_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while deleting files.", "error": str(e)})

async def delete_agent_custom_data_controller(requestData: dict, userData: dict):
    """
    Controller to delete custom data (custom_texts and qa_pairs) from an agent.
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_modify(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        user_id = auth_result
        custom_texts = requestData.get("custom_texts")
        qa_pairs = requestData.get("qa_pairs")

        # Validate that at least one of custom_texts or qa_pairs is present
        if not custom_texts and not qa_pairs:
            return JSONResponse(status_code=400, content={"success": False, "message": "At least one of custom_texts or qa_pairs must be provided."})
        
        # Validate custom_texts if present
        if custom_texts is not None:
            if not isinstance(custom_texts, list):
                return JSONResponse(status_code=400, content={"success": False, "message": "custom_texts must be a list."})
        
        # Validate qa_pairs if present
        if qa_pairs is not None:
            if not isinstance(qa_pairs, list):
                return JSONResponse(status_code=400, content={"success": False, "message": "qa_pairs must be a list."})
        
        logger.info(f"Deleting custom data for agent_id: {agent_id} by user_id: {user_id} - "
                   f"custom_texts: {len(custom_texts) if custom_texts else 0}, "
                   f"qa_pairs: {len(qa_pairs) if qa_pairs else 0}")
        
        result = await remove_custom_data(agent_id, custom_texts=custom_texts, qa_pairs=qa_pairs)
        
        if result.get("success"):
            return JSONResponse(status_code=200, content={
                "success": True, 
                "message": "We are updating the agent.",
            })
        else:
            return JSONResponse(status_code=500, content={
                "success": False, 
                "message": "Failed to delete custom data.", 
                "errors": result.get("errors", [])
            })
    
    except Exception as e:
        logger.error(f"Error in delete_agent_custom_data_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while processing custom data deletion.", "error": str(e)})

async def get_custom_text_content_controller(requestData: dict, userData: dict):
    """
    Controller to retrieve and reconstruct custom text content from Qdrant chunks.
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_read(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        user_id = auth_result
        custom_text_alias = requestData.get("custom_text_alias")

        if not custom_text_alias:
            return JSONResponse(status_code=400, content={"success": False, "message": "custom_text_alias is required."})
        
        logger.info(f"Retrieving custom text for agent_id: {agent_id}, custom_text_alias: {custom_text_alias} by user_id: {user_id}")
        
        result = await get_custom_text_from_qdrant(agent_id, custom_text_alias)
        
        if result.get("success"):
            return JSONResponse(status_code=200, content={
                "success": True,
                "text_content": result.get("text_content"),
                "chunks_count": result.get("chunks_count"),
                "message": result.get("message", "Custom text retrieved successfully.")
            })
        else:
            return JSONResponse(status_code=500, content={
                "success": False,
                "message": "Failed to retrieve custom text.",
                "errors": result.get("errors", [])
            })
    
    except Exception as e:
        logger.error(f"Error in get_custom_text_content_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while retrieving custom text.", "error": str(e)})

async def get_qa_pair_content_controller(requestData: dict, userData: dict):
    """
    Controller to retrieve QA pair content from Qdrant.
    """
    try:
        agent_id = requestData.get("agent_id")
        auth_result = await _require_agent_read(userData, agent_id)
        if isinstance(auth_result, JSONResponse):
            return auth_result

        user_id = auth_result
        qna_alias = requestData.get("qna_alias")

        if not qna_alias:
            return JSONResponse(status_code=400, content={"success": False, "message": "qna_alias is required."})
        
        logger.info(f"Retrieving QA pair for agent_id: {agent_id}, qna_alias: {qna_alias} by user_id: {user_id}")
        
        result = await get_qa_pair_from_qdrant(agent_id, qna_alias)
        
        if result.get("success"):
            return JSONResponse(status_code=200, content={
                "success": True,
                "question": result.get("question"),
                "answer": result.get("answer"),
                "text_content": result.get("text_content"),
                "message": result.get("message", "QA pair retrieved successfully.")
            })
        else:
            return JSONResponse(status_code=500, content={
                "success": False,
                "message": "Failed to retrieve QA pair.",
                "errors": result.get("errors", [])
            })
    
    except Exception as e:
        logger.error(f"Error in get_qa_pair_content_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while retrieving QA pair.", "error": str(e)})   