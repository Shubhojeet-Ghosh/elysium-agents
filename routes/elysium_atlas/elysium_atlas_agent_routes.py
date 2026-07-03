from fastapi import APIRouter
from typing import Dict, Any
from fastapi import Depends
from middlewares.jwt_middleware import authorize_user
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from config.atlas_agent_models import ListAgentsRequest, ListAgentAttachedKbItemsRequest
from controllers.elysium_atlas_controller_files.atlas_controllers import (
    build_update_agent_controller_v1,
    pre_build_agent_operations_controller,
    list_agents_controller,
    delete_agent_controller,
    get_agent_details_controller,
    update_agent_controller_v1,
    get_agent_fields_controller,
)
from controllers.elysium_atlas_controller_files.atlas_agent_kb_controllers import (
    list_attached_urls_controller,
    list_attached_files_controller,
    list_attached_custom_texts_controller,
    list_attached_qa_pairs_controller,
)
from controllers.elysium_atlas_controller_files.atlas_chat_controllers import (
    chat_with_agent_controller_v1,
    rotate_conversation_id_controller,
    mark_chat_message_read_controller,
)

elysium_atlas_agent_router = APIRouter(prefix="/elysium-atlas/agent", tags=["Elysium Atlas - Agent Routes"])

@elysium_atlas_agent_router.post("/v1/pre-build-agent-operations")
async def pre_build_agent_operations_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await pre_build_agent_operations_controller(requestData, user)

@elysium_atlas_agent_router.post("/v1/build-agent")
async def build_update_agent_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user), background_tasks: BackgroundTasks = BackgroundTasks()):
    return await build_update_agent_controller_v1(requestData, user, background_tasks)

@elysium_atlas_agent_router.post("/v1/list-agents")
async def list_agents_route_v1(body: ListAgentsRequest, user: dict = Depends(authorize_user)):
    return await list_agents_controller(body, user)

@elysium_atlas_agent_router.post("/v1/delete-agent")
async def delete_agent_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await delete_agent_controller(requestData, user)

@elysium_atlas_agent_router.post("/v1/get-agent-details")
async def get_agent_details_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await get_agent_details_controller(requestData, user)

@elysium_atlas_agent_router.post("/v1/list-attached-urls")
async def list_attached_urls_route_v1(body: ListAgentAttachedKbItemsRequest, user: dict = Depends(authorize_user)):
    return await list_attached_urls_controller(body, user)

@elysium_atlas_agent_router.post("/v1/list-attached-files")
async def list_attached_files_route_v1(body: ListAgentAttachedKbItemsRequest, user: dict = Depends(authorize_user)):
    return await list_attached_files_controller(body, user)

@elysium_atlas_agent_router.post("/v1/list-attached-custom-texts")
async def list_attached_custom_texts_route_v1(body: ListAgentAttachedKbItemsRequest, user: dict = Depends(authorize_user)):
    return await list_attached_custom_texts_controller(body, user)

@elysium_atlas_agent_router.post("/v1/list-attached-qa-pairs")
async def list_attached_qa_pairs_route_v1(body: ListAgentAttachedKbItemsRequest, user: dict = Depends(authorize_user)):
    return await list_attached_qa_pairs_controller(body, user)

@elysium_atlas_agent_router.post("/v1/get-agent-fields")
async def get_agent_fields_route_v1(requestData: Dict[str, Any]):
    return await get_agent_fields_controller(requestData)

@elysium_atlas_agent_router.post("/v1/update-agent")
async def update_agent_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user), background_tasks: BackgroundTasks = BackgroundTasks()):
    return await update_agent_controller_v1(requestData, user, background_tasks)

@elysium_atlas_agent_router.post("/v1/query-agent")
async def query_agent_route_v1(requestData: Dict[str, Any], user: dict = Depends(authorize_user)):
    return await chat_with_agent_controller_v1(requestData, user)

@elysium_atlas_agent_router.post("/v1/rotate-conversation-id")
async def rotate_conversation_id_route_v1(requestData: Dict[str, Any]):
    return await rotate_conversation_id_controller(requestData)

@elysium_atlas_agent_router.post("/v1/mark-chat-message-read")
async def mark_chat_message_read_route_v1(requestData: Dict[str, Any]):
    return await mark_chat_message_read_controller(requestData)
