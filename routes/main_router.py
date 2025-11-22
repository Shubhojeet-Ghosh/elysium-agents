from fastapi import APIRouter
from config.settings import settings

from routes.elysium_atlas.elysium_atlas_routes import elysium_atlas_router

# Create the main router with a prefix
main_router = APIRouter(prefix = "/elysium-agents")

main_router.include_router(elysium_atlas_router)