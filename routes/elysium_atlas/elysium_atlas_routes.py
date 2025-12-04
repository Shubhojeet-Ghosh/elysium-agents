from typing import Dict, Any
from fastapi import Depends
from middlewares.jwt_middleware import authorize_user

from controller.elysium_atlas_controller_files.atlas_url_controllers import (
    ping_url_controller,
    scrape_urls_controller,
    extract_url_links_controller
)

from fastapi import APIRouter

elysium_atlas_router = APIRouter(prefix = "/elysium-atlas",tags=["Elysium Atlas"])

# Async POST method to ping a URL and check if it is reachable
@elysium_atlas_router.post("/v1/ping-url")
async def ping_url_route(requestData: Dict[str, Any]):
    return await ping_url_controller(requestData)

# Async POST method to scrape URLs and get the html content, text content, hrefs, etc.
@elysium_atlas_router.post("/v1/scrape-urls")
async def scrape_urls_route(requestData: Dict[str, Any],user: dict = Depends(authorize_user)):
    return await scrape_urls_controller(requestData,user)

# Async POST method to get all the links for a given link or from a sitemap
@elysium_atlas_router.post("/v1/extract-url-links")
async def extract_url_links_route(requestData: Dict[str, Any],user: dict = Depends(authorize_user)):
    return await extract_url_links_controller(requestData,user)
