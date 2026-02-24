from fastapi import APIRouter
from typing import Dict, Any
from fastapi import Depends
from middlewares.jwt_middleware import authorize_user

from controllers.elysium_atlas_controller_files.atlas_visitors_controllers import get_agents_visitor_counts_controller

atlas_visitors_router = APIRouter(prefix="/atlas-visitors", tags=["Atlas Visitors"])


@atlas_visitors_router.post("/get-visitor-counts")
async def get_agents_visitor_counts(user: dict = Depends(authorize_user)):
    return await get_agents_visitor_counts_controller(user)