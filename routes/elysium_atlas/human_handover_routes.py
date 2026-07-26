from fastapi import APIRouter, Depends

from config.human_handover_models import (
    GetHumanHandoverConfigRequest,
    ResetHumanHandoverConfigRequest,
    UpdateHumanHandoverConfigRequest,
    VisitorHandoverContactDeclineRequest,
    VisitorHandoverContactRequest,
)
from controllers.elysium_atlas_controller_files.human_handover_controllers import (
    get_human_handover_config_controller,
    reset_human_handover_config_controller,
    update_human_handover_config_controller,
    visitor_handover_contact_controller,
    visitor_handover_contact_decline_controller,
)
from middlewares.jwt_middleware import authorize_user

human_handover_router = APIRouter(
    prefix="/elysium-atlas/human-handover",
    tags=["Elysium Atlas - Human Handover"],
)


@human_handover_router.post("/v1/get-config")
async def get_human_handover_config_route(
    body: GetHumanHandoverConfigRequest,
    user: dict = Depends(authorize_user),
):
    return await get_human_handover_config_controller(body, user)


@human_handover_router.post("/v1/update-config")
async def update_human_handover_config_route(
    body: UpdateHumanHandoverConfigRequest,
    user: dict = Depends(authorize_user),
):
    return await update_human_handover_config_controller(body, user)


@human_handover_router.post("/v1/reset-config")
async def reset_human_handover_config_route(
    body: ResetHumanHandoverConfigRequest,
    user: dict = Depends(authorize_user),
):
    return await reset_human_handover_config_controller(body, user)


@human_handover_router.post("/v1/submit-contact")
async def visitor_handover_contact_route(body: VisitorHandoverContactRequest):
    return await visitor_handover_contact_controller(body)


@human_handover_router.post("/v1/decline-contact")
async def visitor_handover_contact_decline_route(body: VisitorHandoverContactDeclineRequest):
    return await visitor_handover_contact_decline_controller(body)
