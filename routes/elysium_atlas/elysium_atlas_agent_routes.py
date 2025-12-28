from fastapi import APIRouter
from typing import Dict, Any
from fastapi import Depends
from middlewares.jwt_middleware import authorize_user
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from controllers.elysium_atlas_controller_files.atlas_controllers import build_update_agent_controller_v1, pre_build_agent_operations_controller,generate_presigned_url_controller, list_agents_controller, delete_agent_controller,get_agent_details_controller,update_agent_controller_v1

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

# Async POST method to build the agent
@elysium_atlas_agent_router.post("/v1/update-agent")
async def update_agent_route_v1(requestData: Dict[str, Any],user: dict = Depends(authorize_user),background_tasks: BackgroundTasks = BackgroundTasks()):
    return await update_agent_controller_v1(requestData,user,background_tasks)