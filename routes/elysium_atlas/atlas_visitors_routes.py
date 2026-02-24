from fastapi import APIRouter
from controllers.elysium_atlas_controller_files.atlas_visitors_controllers import get_agents_visitor_counts_controller

atlas_visitors_router = APIRouter(prefix="/atlas-visitors", tags=["Atlas Visitors"])


@atlas_visitors_router.post("/get-visitor-counts")
async def get_agents_visitor_counts(requestData: dict):
    return await get_agents_visitor_counts_controller(requestData)
