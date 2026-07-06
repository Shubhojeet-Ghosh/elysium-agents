from fastapi import APIRouter, Depends

from config.lead_collection_models import (
    GetLeadCollectionConfigRequest,
    ResetLeadCollectionConfigRequest,
    UpdateLeadCollectionConfigRequest,
    UpdateSessionLeadRequest,
)
from controllers.elysium_atlas_controller_files.lead_collection_controllers import (
    get_lead_collection_config_controller,
    get_lead_collection_field_catalog_controller,
    reset_lead_collection_config_controller,
    update_lead_collection_config_controller,
    update_session_lead_controller,
)
from middlewares.jwt_middleware import authorize_user

lead_collection_router = APIRouter(
    prefix="/elysium-atlas/lead-collection",
    tags=["Elysium Atlas - Lead Collection"],
)


@lead_collection_router.post("/v1/get-config")
async def get_lead_collection_config_route(
    body: GetLeadCollectionConfigRequest,
    user: dict = Depends(authorize_user),
):
    return await get_lead_collection_config_controller(body, user)


@lead_collection_router.post("/v1/update-config")
async def update_lead_collection_config_route(
    body: UpdateLeadCollectionConfigRequest,
    user: dict = Depends(authorize_user),
):
    return await update_lead_collection_config_controller(body, user)


@lead_collection_router.post("/v1/reset-config")
async def reset_lead_collection_config_route(
    body: ResetLeadCollectionConfigRequest,
    user: dict = Depends(authorize_user),
):
    return await reset_lead_collection_config_controller(body, user)


@lead_collection_router.post("/v1/get-field-catalog")
async def get_lead_collection_field_catalog_route(user: dict = Depends(authorize_user)):
    return await get_lead_collection_field_catalog_controller(user)


@lead_collection_router.post("/v1/update-session-lead")
async def update_session_lead_route(
    body: UpdateSessionLeadRequest,
    user: dict = Depends(authorize_user),
):
    return await update_session_lead_controller(body, user)
