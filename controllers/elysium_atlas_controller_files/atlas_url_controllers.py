from typing import Dict, Any
from fastapi.responses import JSONResponse
from services.web_services.url_services import *
from services.web_services.sitemap_services import extract_urls_from_sitemap

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

async def scrape_urls_controller(requestData: Dict[str, Any],userData: dict):
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})

        if(userData.get("success")):
            logger.info(f"User data: {userData}")
            
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

async def extract_url_links_controller(requestData: Dict[str, Any],userData: dict):
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})

        if(userData.get("success")):
            logger.info(f"User data: {userData}")

        source = requestData.get("source")
        if not source:
            return JSONResponse(status_code=400, content={"success": False, "message": "Source is required"})
        
        link = requestData.get("link")
        if not link:
            return JSONResponse(status_code=400, content={"success": False, "message": "Link is required"})
        
        if source == "url":
            
            normalized_url = normalize_url(link)

            # Call fetch_multiple_urls_content with link in a list
            results = await fetch_multiple_urls_content([link])
            
            # Check if we got a result
            if not results or len(results) == 0:
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "message": "Failed to fetch URL content"}
                )
            
            # Get the first result (since we passed a single URL)
            result = results[0]
            
            # Extract hrefs from the result
            links = result.get("hrefs", [])
            
            # Filter out invalid and unnecessary links
            filtered_links = filter_urls(links)
            
            # Return success response with filtered links
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Successfully extracted links from URL",
                    "links": filtered_links,
                    "links_count": len(filtered_links),
                    "base_url": normalized_url,
                }
            )

        elif source == "sitemap":
            # Extract URLs from sitemap (normalization is handled inside the function)
            result = await extract_urls_from_sitemap(link)
            
            # Check if extraction was successful
            if not result.get("success"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": result.get("message", "Failed to extract URLs from sitemap"),
                        "links": result.get("urls", []),
                        "links_count": len(result.get("urls", [])),
                        "error": result.get("error", None)
                    }
                )
            
            # Return success response with links
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": result.get("message", "Successfully extracted links from sitemap"),
                    "links": result.get("urls", []),
                    "links_count": len(result.get("urls", [])),
                    "base_url": result.get("base_url", None),
                }
            )
        else:
            return JSONResponse(status_code=400, content={"success": False, "message": "Invalid source"})

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Something went wrong while extracting URL links.",
                "error": str(e)
            }
        )