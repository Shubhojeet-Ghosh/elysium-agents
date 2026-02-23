from fastapi import APIRouter
from typing import Dict, Any
from fastapi import Depends
from middlewares.jwt_middleware import authorize_user
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from controllers.elysium_atlas_controller_files.atlas_controllers import build_update_agent_controller_v1, pre_build_agent_operations_controller,generate_presigned_url_controller, list_agents_controller, delete_agent_controller,get_agent_details_controller,update_agent_controller_v1, get_agent_fields_controller, get_agent_urls_controller, get_agent_files_controller, get_agent_custom_texts_controller, get_agent_qa_pairs_controller, remove_agent_links_controller, delete_agent_files_controller, delete_agent_custom_data_controller, get_custom_text_content_controller, get_qa_pair_content_controller
from controllers.elysium_atlas_controller_files.atlas_chat_controllers import chat_with_agent_controller_v1, rotate_conversation_id_controller

elysium_atlas_agent_router = APIRouter(prefix = "/elysium-atlas/agent",tags=["Elysium Atlas - Agent Routes"])

# Async POST method to build the agent
@elysium_atlas_agent_router.post("/v1/pre-build-agent-operations")
async def pre_build_agent_operations_route_v1(requestData: Dict[str, Any],user: dict = Depends(authorize_user)):
    return await pre_build_agent_operations_controller(requestData,user)

# Async POST method to generate presigned urls for the agent
@elysium_atlas_agent_router.post("/v1/generate-presigned-urls")
async def generate_presigned_urls_route_v1(requestData: Dict[str, Any],user: dict = Depends(authorize_user)):
    return await generate_presigned_url_controller(requestData,user)

# Async POST method to build the agent
@elysium_atlas_agent_router.post("/v1/build-agent")
async def build_update_agent_route_v1(requestData: Dict[str, Any],user: dict = Depends(authorize_user),background_tasks: BackgroundTasks = BackgroundTasks()):
    return await build_update_agent_controller_v1(requestData,user,background_tasks)

# Async POST method to list all agents for a user
@elysium_atlas_agent_router.post("/v1/list-agents")
async def list_agents_route_v1(user: dict = Depends(authorize_user)):
    return await list_agents_controller(user)

# Async POST method to delete an agent
@elysium_atlas_agent_router.post("/v1/delete-agent")
async def delete_agent_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await delete_agent_controller(requestData, user)

# Async POST method to get the details of an agent
@elysium_atlas_agent_router.post("/v1/get-agent-details")
async def get_agent_details_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await get_agent_details_controller(requestData, user)

# Async POST method to get specific fields of an agent
@elysium_atlas_agent_router.post("/v1/get-agent-fields")
async def get_agent_fields_route_v1(requestData: Dict[str, Any]):
    return await get_agent_fields_controller(requestData)

# Async POST method to build the agent
@elysium_atlas_agent_router.post("/v1/update-agent")
async def update_agent_route_v1(requestData: Dict[str, Any],user: dict = Depends(authorize_user),background_tasks: BackgroundTasks = BackgroundTasks()):
    return await update_agent_controller_v1(requestData,user,background_tasks)

# Async POST method to query the agent
@elysium_atlas_agent_router.post("/v1/query-agent")
async def query_agent_route_v1(requestData: Dict[str, Any],user: dict = Depends(authorize_user)):
    return await chat_with_agent_controller_v1(requestData,user)

# Async POST method to get paginated agent URLs
@elysium_atlas_agent_router.post("/v1/get-agent-urls")
async def get_agent_urls_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await get_agent_urls_controller(requestData, user)

# Async POST method to get paginated agent files
@elysium_atlas_agent_router.post("/v1/get-agent-files")
async def get_agent_files_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await get_agent_files_controller(requestData, user)

# Async POST method to get paginated agent custom texts
@elysium_atlas_agent_router.post("/v1/get-agent-custom-texts")
async def get_agent_custom_texts_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await get_agent_custom_texts_controller(requestData, user)

# Async POST method to get paginated agent QA pairs
@elysium_atlas_agent_router.post("/v1/get-agent-qa-pairs")
async def get_agent_qa_pairs_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await get_agent_qa_pairs_controller(requestData, user)

# Async POST method to remove specific links from an agent
@elysium_atlas_agent_router.post("/v1/remove-agent-links")
async def remove_agent_links_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await remove_agent_links_controller(requestData, user)

# Async POST method to delete specific files from an agent
@elysium_atlas_agent_router.post("/v1/delete-agent-files")
async def delete_agent_files_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await delete_agent_files_controller(requestData, user)

# Async POST method to delete custom data (custom_texts and qa_pairs) from an agent
@elysium_atlas_agent_router.post("/v1/delete-agent-custom-data")
async def delete_agent_custom_data_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await delete_agent_custom_data_controller(requestData, user)

# Async POST method to retrieve custom text content from Qdrant chunks
@elysium_atlas_agent_router.post("/v1/get-custom-text-content")
async def get_custom_text_content_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await get_custom_text_content_controller(requestData, user)

# Async POST method to retrieve QA pair content from Qdrant
@elysium_atlas_agent_router.post("/v1/get-qa-pair-content")
async def get_qa_pair_content_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await get_qa_pair_content_controller(requestData, user)

# Async POST method to rotate (start a new) conversation under an existing chat session
@elysium_atlas_agent_router.post("/v1/rotate-conversation-id")
async def rotate_conversation_id_route_v1(requestData: Dict[str, Any]):
    return await rotate_conversation_id_controller(requestData)