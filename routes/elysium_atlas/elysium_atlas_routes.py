from typing import Dict, Any

from controller.elysium_atlas_controller_files.atlas_url_controllers import ping_url_controller, scrape_urls_controller

from fastapi import APIRouter

elysium_atlas_router = APIRouter(prefix = "/elysium-atlas",tags=["Elysium Atlas"])

# Async POST method to ping a URL and check if it is reachable
@elysium_atlas_router.post("/v1/ping-url")
async def ping_url_route(requestData: Dict[str, Any]):
    return await ping_url_controller(requestData)

# Async POST method to scrape URLs and get the html content, text content, hrefs, etc.
@elysium_atlas_router.post("/v1/scrape-urls")
async def scrape_urls_route(requestData: Dict[str, Any]):
    return await scrape_urls_controller(requestData)