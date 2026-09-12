from fastapi import APIRouter, Depends

from config.atlas_plugin_models import (
    CreatePluginRequest,
    DeletePluginRequest,
    GetPluginRequest,
    ListPluginsRequest,
    SetPluginSecretsRequest,
    TestPluginRequest,
    UpdatePluginRequest,
)
from controllers.elysium_atlas_controller_files.atlas_plugin_controllers import (
    create_plugin_controller,
    delete_plugin_controller,
    get_plugin_controller,
    list_plugins_controller,
    set_plugin_secrets_controller,
    test_plugin_controller,
    update_plugin_controller,
)
from middlewares.jwt_middleware import authorize_user

atlas_plugins_router = APIRouter(prefix="/elysium-atlas/plugins", tags=["Elysium Atlas - Plugins"])


@atlas_plugins_router.post("/v1/create-plugin")
async def create_plugin_route(body: CreatePluginRequest, user: dict = Depends(authorize_user)):
    return await create_plugin_controller(body, user)


@atlas_plugins_router.post("/v1/list-plugins")
async def list_plugins_route(body: ListPluginsRequest, user: dict = Depends(authorize_user)):
    return await list_plugins_controller(body, user)


@atlas_plugins_router.post("/v1/get-plugin")
async def get_plugin_route(body: GetPluginRequest, user: dict = Depends(authorize_user)):
    return await get_plugin_controller(body, user)


@atlas_plugins_router.post("/v1/update-plugin")
async def update_plugin_route(body: UpdatePluginRequest, user: dict = Depends(authorize_user)):
    return await update_plugin_controller(body, user)


@atlas_plugins_router.post("/v1/delete-plugin")
async def delete_plugin_route(body: DeletePluginRequest, user: dict = Depends(authorize_user)):
    return await delete_plugin_controller(body, user)


@atlas_plugins_router.post("/v1/set-plugin-secrets")
async def set_plugin_secrets_route(body: SetPluginSecretsRequest, user: dict = Depends(authorize_user)):
    return await set_plugin_secrets_controller(body, user)


@atlas_plugins_router.post("/v1/test-plugin")
async def test_plugin_route(body: TestPluginRequest, user: dict = Depends(authorize_user)):
    return await test_plugin_controller(body, user)
