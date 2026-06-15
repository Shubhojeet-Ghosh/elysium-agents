from fastapi import APIRouter, Depends

from config.atlas_tool_models import (
    CreateToolRequest,
    DeleteToolRequest,
    GetToolRequest,
    ListToolsRequest,
    UpdateToolRequest,
)
from controllers.elysium_atlas_controller_files.atlas_tool_controllers import (
    create_tool_controller,
    delete_tool_controller,
    get_tool_controller,
    list_tools_controller,
    update_tool_controller,
)
from middlewares.jwt_middleware import authorize_user

atlas_tools_router = APIRouter(prefix="/elysium-atlas/tools", tags=["Elysium Atlas - Tools"])


@atlas_tools_router.post("/v1/create-tool")
async def create_tool_route(body: CreateToolRequest, user: dict = Depends(authorize_user)):
    return await create_tool_controller(body, user)


@atlas_tools_router.post("/v1/list-tools")
async def list_tools_route(body: ListToolsRequest, user: dict = Depends(authorize_user)):
    return await list_tools_controller(body, user)


@atlas_tools_router.post("/v1/get-tool")
async def get_tool_route(body: GetToolRequest, user: dict = Depends(authorize_user)):
    return await get_tool_controller(body, user)


@atlas_tools_router.post("/v1/update-tool")
async def update_tool_route(body: UpdateToolRequest, user: dict = Depends(authorize_user)):
    return await update_tool_controller(body, user)


@atlas_tools_router.post("/v1/delete-tool")
async def delete_tool_route(body: DeleteToolRequest, user: dict = Depends(authorize_user)):
    return await delete_tool_controller(body, user)
