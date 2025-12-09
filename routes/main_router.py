from fastapi import APIRouter
from config.settings import settings

from routes.elysium_atlas.elysium_atlas_routes import elysium_atlas_router
from routes.elysium_atlas.user_auth_routes import elysium_atlas_user_auth_router
from routes.elysium_atlas.elysium_atlas_agent_routes import elysium_atlas_agent_router

# Create the main router with a prefix
main_router = APIRouter(prefix = "/elysium-agents")

main_router.include_router(elysium_atlas_router)
main_router.include_router(elysium_atlas_user_auth_router)
main_router.include_router(elysium_atlas_agent_router)