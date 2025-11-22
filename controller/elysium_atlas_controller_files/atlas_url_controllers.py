from typing import Dict, Any
from fastapi.responses import JSONResponse
from services.url_services import *

async def ping_url_controller(requestData: Dict[str, Any]):
    try:
        url = requestData.get("url")
        
        # Early validation to fail fast on invalid URLs
        if not url:
            return JSONResponse(status_code=400, content={"success": False, "message": "URL is required"})
        
        if not validate_url_format(url):
            return JSONResponse(status_code=400, content={"success": False, "message": "Invalid URL format"})
        
        url_response = await is_url_reachable(url)
        return JSONResponse(status_code=200, content={"success": True, "message": "URL is reachable", "data": url_response})

    except Exception as e:
        return ({
            "success": False,
            "message": f"An error occurred while pinging the URL.",
            "error": str(e)
        })

async def scrape_urls_controller(requestData: Dict[str, Any]):
    try:
        urls = requestData.get("urls") or requestData.get("url")
        
        # Handle both single URL (string) and multiple URLs (list)
        if not urls:
            return JSONResponse(status_code=400, content={"success": False, "message": "URLs are required"})
        
        # Convert single URL to list for consistent processing
        if isinstance(urls, str):
            urls = [urls]
        
        if not isinstance(urls, list):
            return JSONResponse(status_code=400, content={"success": False, "message": "URLs must be a list or string"})
        
        if len(urls) == 0:
            return JSONResponse(status_code=400, content={"success": False, "message": "At least one URL is required"})
        
        # Use the comprehensive service function to process all URLs
        results = await fetch_multiple_urls_content(urls)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Processed {len(urls)} URL(s)",
                "data": results
            }
        )

    except Exception as e:
        return ({
            "success": False,
            "message": f"An error occurred while scraping URLs.",
            "error": str(e)
        })