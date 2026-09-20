from fastapi import APIRouter, Depends

from config.atlas_dashboard_models import ChatSessionCountsRequest
from controllers.elysium_atlas_controller_files.atlas_dashboard_controllers import (
    get_chat_session_counts_controller,
)
from middlewares.jwt_middleware import authorize_user

atlas_dashboard_router = APIRouter(
    prefix="/elysium-atlas/dashboard",
    tags=["Elysium Atlas - Dashboard"],
)


@atlas_dashboard_router.post("/v1/chat-session-counts")
async def get_chat_session_counts_route(
    body: ChatSessionCountsRequest,
    user: dict = Depends(authorize_user),
):
    return await get_chat_session_counts_controller(body, user)
