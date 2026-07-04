from fastapi import APIRouter
from typing import Optional
from fastapi import Depends, Query
from middlewares.application_passkey_auth import verify_application_passkey
from middlewares.jwt_middleware import authorize_user

from controllers.elysium_atlas_controller_files.atlas_stale_visitor_controllers import cleanup_stale_visitors_controller
from controllers.elysium_atlas_controller_files.atlas_visitors_controllers import (
    get_agent_chat_sessions_summary_controller,
)

atlas_visitors_router = APIRouter(prefix="/atlas-visitors", tags=["Atlas Visitors"])


@atlas_visitors_router.get("/chat-sessions-summary")
async def get_chat_sessions_summary(
    agent_id: str = Query(..., description="Agent to summarize."),
    user: dict = Depends(authorize_user),
):
    """
    Lightweight counts for the agent chat sessions dashboard.

    Poll this endpoint when the tab is focused to detect new sessions without
    socket fan-out. Refetch the full list only when the user clicks refresh.
    """
    return await get_agent_chat_sessions_summary_controller(user, agent_id=agent_id)


@atlas_visitors_router.get("/cleanup-stale-visitors")
async def cleanup_stale_visitors(
    authorized: bool = Depends(verify_application_passkey),
    threshold_seconds: Optional[int] = Query(
        default=None,
        description="Override stale threshold in seconds (default from visitor_presence_config).",
    ),
):
    return await cleanup_stale_visitors_controller(
        authorized,
        threshold_seconds=threshold_seconds,
    )