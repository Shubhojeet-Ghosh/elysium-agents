from fastapi import APIRouter
from typing import Dict, Any
from fastapi import Depends
from middlewares.jwt_middleware import authorize_user
from fastapi import BackgroundTasks

from controller.elysium_atlas_controller_files.atlas_controllers import build_agent_controller_v1, pre_build_agent_operations_controller

elysium_atlas_agent_router = APIRouter(prefix = "/elysium-atlas/agent",tags=["Elysium Atlas - Agent Routes"])

# Async POST method to build the agent
@elysium_atlas_agent_router.post("/v1/pre-build-agent-operations")
async def pre_build_agent_operations_route_v1(requestData: Dict[str, Any],user: dict = Depends(authorize_user)):
    return await pre_build_agent_operations_controller(requestData,user)

# Async POST method to build the agent
@elysium_atlas_agent_router.post("/v1/build-agent")
async def build_agent_route_v1(requestData: Dict[str, Any],user: dict = Depends(authorize_user),background_tasks: BackgroundTasks = BackgroundTasks()):
    return await build_agent_controller_v1(requestData,user,background_tasks)