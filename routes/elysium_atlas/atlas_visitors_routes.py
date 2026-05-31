from fastapi import APIRouter
from typing import Dict, Any, Optional
from fastapi import Depends, Query
from middlewares.jwt_middleware import authorize_user
from middlewares.application_passkey_auth import verify_application_passkey

from controllers.elysium_atlas_controller_files.atlas_visitors_controllers import get_agents_visitor_counts_controller
from controllers.elysium_atlas_controller_files.atlas_stale_visitor_controllers import cleanup_stale_visitors_controller

atlas_visitors_router = APIRouter(prefix="/atlas-visitors", tags=["Atlas Visitors"])


@atlas_visitors_router.post("/get-visitor-counts")
async def get_agents_visitor_counts(user: dict = Depends(authorize_user)):
    return await get_agents_visitor_counts_controller(user)


@atlas_visitors_router.get("/cleanup-stale-visitors")
async def cleanup_stale_visitors(
    authorized: bool = Depends(verify_application_passkey),
    threshold_seconds: Optional[int] = Query(
        default=None,
        description="Override stale threshold in seconds (default from visitor_presence_config).",
    ),
    emit_events: bool = Query(
        default=True,
        description="Emit agent_visitor_disconnected and agent_visitor_count_updated socket events.",
    ),
):
    return await cleanup_stale_visitors_controller(
        authorized,
        threshold_seconds=threshold_seconds,
        emit_events=emit_events,
    )