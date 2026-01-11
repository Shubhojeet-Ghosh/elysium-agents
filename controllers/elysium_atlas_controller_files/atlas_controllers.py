import asyncio
from typing import Dict, Any
from fastapi.responses import JSONResponse
from logging_config import get_logger
from services.elysium_atlas_services.agent_services import initialize_agent_build_update, create_agent_document, list_agents_for_user, remove_agent_by_id,fetch_agent_details_by_id,initialize_agent_update, fetch_agent_fields_by_id, fetch_agent_urls, fetch_agent_files, fetch_agent_custom_knowledge, remove_agent_links, remove_agent_files
from services.elysium_atlas_services.agent_auth_services import is_user_owner_of_agent
from services.elysium_atlas_services.atlas_chat_session_services import get_chat_session_data
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from config.elysium_atlas_s3_config import ELYSIUM_ATLAS_BUCKET_NAME, ELYSIUM_CDN_BASE_URL, ELYSIUM_GLOBAL_BUCKET_NAME
from services.aws_services.s3_service import generate_presigned_upload_url
from services.elysium_atlas_services.agent_db_operations import check_agent_name_exists
from services.elysium_atlas_services.agent_db_operations import update_agent_status

logger = get_logger()

async def pre_build_agent_operations_controller(requestData: Dict[str, Any],userData: dict):
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        # logger.info(f"User data: {userData}")

        user_id = userData.get("user_id")

        initial_data = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_init_config")
        
        initial_data["owner_user_id"] = user_id

        if requestData.get("agent_name") is not None:
            agent_exists = await check_agent_name_exists(user_id, requestData.get("agent_name"))
            if agent_exists:
                return JSONResponse(status_code=200, content={"success": False, "message": "An agent with this name already exists. Please choose a different name."})
            
            initial_data["agent_name"] = requestData.get("agent_name")

        agent_id = await create_agent_document(initial_data)
        if agent_id is None:
            return JSONResponse(status_code=500, content={"success": False, "message": "Failed to create the agent."})
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Agent created successfully.", "agent_id": agent_id})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while building the agent.", "error": str(e)})

async def build_update_agent_controller_v1(requestData,userData,background_tasks):
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        logger.info(f"User data: {userData}")
        
        agent_id = requestData.get("agent_id")
        if not agent_id:
            agent_id = await create_agent_document()
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
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        logger.info(f"User data: {userData}")
        
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

async def list_agents_controller(userData: dict):
    """
    Controller to handle the logic for listing all agents for a given user_id.

    Returns:
        JSONResponse: A response containing the list of agents or an error message.
    """
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")

        if not user_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required to list agents."})
        
        logger.info(f"Listing agents for user_id: {user_id}")
        agents = await list_agents_for_user(user_id)
        return JSONResponse(status_code=200, content={"success": True, "agents": agents})

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
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        logger.info(f"User data: {userData}")

        user_id = userData.get("user_id")

        if not user_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})
        
        agent_id = requestData.get("agent_id")
        logger.info(f"Request to delete agent_id: {agent_id} by user_id: {user_id}")

        # Check if the user is the owner of the agent
        is_owner = await is_user_owner_of_agent(user_id, agent_id)

        if not is_owner:
            return JSONResponse(status_code=403, content={"success": False, "message": "You are not authorized to delete this agent."})

        # Proceed to delete the agent
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
        
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")
        agent_id = requestData.get("agent_id")

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
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
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        # logger.info(f"User data: {userData}")
        
        # logger.info(f"buil/update agent with request data: {requestData}")
        
        agent_id = requestData.get("agent_id")
        if not agent_id:
            logger.error("agent_id is required for update operation")
            return JSONResponse(status_code=400, content={"success": False, "message": "You can't perform update without agent."})
        
        # Set agent status to 'indexing' after creation/update
        await update_agent_status(agent_id, "updating")

        # Store links in MongoDB
        background_tasks.add_task(initialize_agent_update,requestData)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Your agent is being updated.", "agent_id": requestData.get("agent_id")})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while updating the agent.", "error": str(e)})

async def get_agent_urls_controller(requestData: dict, userData: dict):
    """
    Controller to fetch paginated URLs for an agent.
    """
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")
        agent_id = requestData.get("agent_id")
        limit = requestData.get("limit", 50)
        cursor = requestData.get("cursor")
        include_count = requestData.get("include_count", False)

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
        logger.info(f"Fetching URLs for agent_id: {agent_id}, limit: {limit}, cursor: {cursor}, include_count: {include_count}")
        
        result = await fetch_agent_urls(agent_id, limit=limit, cursor=cursor, include_count=include_count)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "URLs fetched successfully.", "urls": result})
    
    except Exception as e:
        logger.error(f"Error in get_agent_urls_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching URLs.", "error": str(e)})

async def get_agent_files_controller(requestData: dict, userData: dict):
    """
    Controller to fetch paginated files for an agent.
    """
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")
        agent_id = requestData.get("agent_id")
        limit = requestData.get("limit", 50)
        cursor = requestData.get("cursor")
        include_count = requestData.get("include_count", False)

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
        logger.info(f"Fetching files for agent_id: {agent_id}, limit: {limit}, cursor: {cursor}, include_count: {include_count}")
        
        result = await fetch_agent_files(agent_id, limit=limit, cursor=cursor, include_count=include_count)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Files fetched successfully.", "files": result})
    
    except Exception as e:
        logger.error(f"Error in get_agent_files_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching files.", "error": str(e)})

async def get_agent_custom_texts_controller(requestData: dict, userData: dict):
    """
    Controller to fetch paginated custom texts for an agent.
    """
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")
        agent_id = requestData.get("agent_id")
        limit = requestData.get("limit", 50)
        cursor = requestData.get("cursor")
        include_count = requestData.get("include_count", False)

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
        logger.info(f"Fetching custom texts for agent_id: {agent_id}, limit: {limit}, cursor: {cursor}, include_count: {include_count}")
        
        result = await fetch_agent_custom_knowledge(agent_id, limit=limit, cursor=cursor, include_count=include_count)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Custom texts fetched successfully.", "custom_texts": result["custom_texts"]})
    
    except Exception as e:
        logger.error(f"Error in get_agent_custom_texts_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching custom texts.", "error": str(e)})

async def get_agent_qa_pairs_controller(requestData: dict, userData: dict):
    """
    Controller to fetch paginated QA pairs for an agent.
    """
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")
        agent_id = requestData.get("agent_id")
        limit = requestData.get("limit", 50)
        cursor = requestData.get("cursor")
        include_count = requestData.get("include_count", False)

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
        logger.info(f"Fetching QA pairs for agent_id: {agent_id}, limit: {limit}, cursor: {cursor}, include_count: {include_count}")
        
        result = await fetch_agent_custom_knowledge(agent_id, limit=limit, cursor=cursor, include_count=include_count)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "QA pairs fetched successfully.", "qa_pairs": result["qa_pairs"]})
    
    except Exception as e:
        logger.error(f"Error in get_agent_qa_pairs_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while fetching QA pairs.", "error": str(e)})

async def remove_agent_links_controller(requestData: dict, userData: dict):
    """
    Controller to remove specific links from an agent (MongoDB and Qdrant).
    """
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")
        agent_id = requestData.get("agent_id")
        links = requestData.get("links")

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
        if not links or not isinstance(links, list) or len(links) == 0:
            return JSONResponse(status_code=400, content={"success": False, "message": "links must be a non-empty list."})
        
        # Check if the user is the owner of the agent
        is_owner = await is_user_owner_of_agent(user_id, agent_id)
        if not is_owner:
            return JSONResponse(status_code=403, content={"success": False, "message": "You are not authorized to modify this agent."})
        
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
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")
        agent_id = requestData.get("agent_id")
        files = requestData.get("files")

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
        if not files or not isinstance(files, list) or len(files) == 0:
            return JSONResponse(status_code=400, content={"success": False, "message": "files must be a non-empty list."})
        
        # Check if the user is the owner of the agent
        is_owner = await is_user_owner_of_agent(user_id, agent_id)
        if not is_owner:
            return JSONResponse(status_code=403, content={"success": False, "message": "You are not authorized to modify this agent."})
        
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
    For now, this only validates and logs the data without actually deleting.
    """
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        user_id = userData.get("user_id")
        agent_id = requestData.get("agent_id")
        custom_texts = requestData.get("custom_texts")
        qa_pairs = requestData.get("qa_pairs")

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
        
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
        
        # Check if the user is the owner of the agent
        is_owner = await is_user_owner_of_agent(user_id, agent_id)
        if not is_owner:
            return JSONResponse(status_code=403, content={"success": False, "message": "You are not authorized to modify this agent."})
        
        # Log the data for now (not deleting anything yet)
        if custom_texts:
            logger.info(f"Custom texts to delete for agent_id: {agent_id} - Count: {len(custom_texts)}")
            logger.info(f"Custom texts list: {custom_texts}")
        
        if qa_pairs:
            logger.info(f"QA pairs to delete for agent_id: {agent_id} - Count: {len(qa_pairs)}")
            logger.info(f"QA pairs list: {qa_pairs}")
        
        return JSONResponse(status_code=200, content={
            "success": True, 
            "message": "We are updating the agent.",
        })
    
    except Exception as e:
        logger.error(f"Error in delete_agent_custom_data_controller: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": "An error occurred while processing custom data deletion.", "error": str(e)})    