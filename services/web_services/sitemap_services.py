"""
Sitemap Services - Extract URLs from sitemaps
"""
import httpx
from typing import List, Set, Dict, Any
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree as ET
from logging_config import get_logger
from services.web_services.url_services import normalize_url

logger = get_logger()


async def extract_urls_from_sitemap(sitemap_url: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Extract all URLs from a sitemap (XML, sitemap index, or text format).
    Handles sitemap index files recursively.
    
    Args:
        sitemap_url: URL of the sitemap to parse
        timeout: Request timeout in seconds (default: 30)
        
    Returns:
        Dictionary with:
            - success: bool - Whether the operation was successful
            - message: str - Success or error message
            - urls: List[str] - List of URLs found (empty list if failed or no URLs found)
    """
    if not sitemap_url or not isinstance(sitemap_url, str):
        logger.warning("Invalid sitemap URL provided")
        return {
            "success": False,
            "message": "Invalid sitemap URL: URL must be a non-empty string",
            "urls": []
        }
    
    sitemap_url = sitemap_url.strip()
    if not sitemap_url:
        logger.warning("Empty sitemap URL provided")
        return {
            "success": False,
            "message": "Invalid sitemap URL: URL cannot be empty",
            "urls": []
        }
    
    # Normalize the sitemap URL (handles missing scheme, www prefix, etc.)
    try:
        normalized_sitemap_url = normalize_url(sitemap_url)
        logger.info(f"Normalized sitemap URL: {sitemap_url} -> {normalized_sitemap_url}")
    except ValueError as e:
        error_msg = f"Invalid sitemap URL format: {str(e)}"
        logger.warning(f"Invalid sitemap URL format: {sitemap_url} - {str(e)}")
        return {
            "success": False,
            "message": "Something went wrong while extracting URLs from sitemap. Please try again with a valid sitemap URL.",
            "urls": [],
            "error": str(e)
        }
    
    try:
        # Fetch the sitemap
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                response = await client.get(normalized_sitemap_url)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP error fetching sitemap: {e.response.status_code}"
                logger.warning(f"HTTP error fetching sitemap {normalized_sitemap_url}: {e.response.status_code}")
                return {
                    "success": False,
                    "message": "Something went wrong while fetching sitemap. Please try again with a valid sitemap URL.",
                    "urls": [],
                    "error": str(error_msg)
                }
            except httpx.RequestError as e:
                error_msg = f"Request error fetching sitemap: {str(e)}"
                logger.warning(f"Request error fetching sitemap {normalized_sitemap_url}: {str(e)}")
                return {
                    "success": False,
                    "message": "Something went wrong while fetching sitemap. Please try again with a valid sitemap URL.",
                    "urls": [],
                    "error": str(error_msg)
                }
            except Exception as e:
                error_msg = f"Error fetching sitemap: {str(e)}"
                logger.warning(f"Error fetching sitemap {normalized_sitemap_url}: {str(e)}")
                return {
                    "success": False,
                    "message": "Something went wrong while fetching sitemap. Please try again with a valid sitemap URL.",
                    "urls": [],
                    "error": str(error_msg)
                }
            
            content_type = response.headers.get("content-type", "").lower()
            content = response.text
            
            if not content:
                logger.warning(f"Empty content from sitemap {normalized_sitemap_url}")
                return {
                    "success": False,
                    "message": "Sitemap URL returned empty content",
                    "urls": []
                }
            
            # Determine sitemap type and parse accordingly
            urls = []
            
            # Check if it's XML (sitemap or sitemap index)
            if "xml" in content_type or content.strip().startswith("<?xml") or content.strip().startswith("<"):
                try:
                    urls = await _parse_xml_sitemap(content, normalized_sitemap_url, client, timeout)
                except Exception as e:
                    error_msg = f"Error parsing XML sitemap: {str(e)}"
                    logger.warning(f"Error parsing XML sitemap {normalized_sitemap_url}: {str(e)}")
                    return {
                        "success": False,
                        "message": "Something went wrong while parsing XML sitemap. Please try again with a valid sitemap URL.",
                        "urls": [],
                        "error": str(error_msg)
                    }
            
            # Check if it's a text sitemap (one URL per line)
            elif "text/plain" in content_type or _is_text_sitemap(content):
                try:
                    urls = _parse_text_sitemap(content)
                except Exception as e:
                    error_msg = f"Error parsing text sitemap: {str(e)}"
                    logger.warning(f"Error parsing text sitemap {normalized_sitemap_url}: {str(e)}")
                    return {
                        "success": False,
                        "message": "Something went wrong while parsing text sitemap. Please try again with a valid sitemap URL.",
                        "urls": [],
                        "error": str(error_msg)
                    }
            
            else:
                # Try to parse as XML first, then as text
                try:
                    urls = await _parse_xml_sitemap(content, normalized_sitemap_url, client, timeout)
                except:
                    try:
                        urls = _parse_text_sitemap(content)
                    except Exception as e:
                        error_msg = f"Could not parse sitemap as XML or text: {str(e)}"
                        logger.warning(f"Could not parse sitemap {normalized_sitemap_url} as XML or text: {str(e)}")
                        return {
                            "success": False,
                            "message": "Something went wrong while extracting URLs from sitemap. Please try again with a valid sitemap URL.",
                            "urls": [],
                            "error": str(e)
                        }
            
            logger.info(f"Extracted {len(urls)} URLs from sitemap {normalized_sitemap_url}")
            return {
                "success": True,
                "message": f"Successfully extracted {len(urls)} URLs from sitemap",
                "urls": urls
            }
            
    except Exception as e:
        error_msg = f"Unexpected error extracting URLs from sitemap: {str(e)}"
        logger.error(f"Unexpected error extracting URLs from sitemap {normalized_sitemap_url if 'normalized_sitemap_url' in locals() else sitemap_url}: {str(e)}")
        return {
            "success": False,
            "message": "Something went wrong while extracting URLs from sitemap. Please try again with a valid sitemap URL.",
            "urls": [],
            "error": str(e)
        }


async def _parse_xml_sitemap(content: str, sitemap_url: str, client: httpx.AsyncClient, timeout: int) -> List[str]:
    """
    Parse XML sitemap or sitemap index.
    Recursively handles sitemap index files.
    
    Args:
        content: XML content as string
        sitemap_url: Original sitemap URL (for resolving relative URLs in sitemap index)
        client: HTTP client for fetching nested sitemaps
        timeout: Request timeout
        
    Returns:
        List of URLs
    """
    urls: Set[str] = set()
    
    try:
        # Parse XML
        root = ET.fromstring(content)
        
        # Check if it's a sitemap index (contains <sitemap> elements)
        if root.tag.endswith("sitemapindex") or root.find(".//{*}sitemap") is not None:
            # It's a sitemap index - recursively fetch all nested sitemaps
            sitemap_elements = root.findall(".//{*}sitemap")
            if not sitemap_elements:
                # Try without namespace
                sitemap_elements = root.findall(".//sitemap")
            
            for sitemap_elem in sitemap_elements:
                loc_elem = sitemap_elem.find("{*}loc")
                if loc_elem is None:
                    # Try without namespace
                    loc_elem = sitemap_elem.find("loc")
                
                if loc_elem is not None and loc_elem.text:
                    nested_sitemap_url = loc_elem.text.strip()
                    # Resolve relative URLs
                    nested_sitemap_url = urljoin(sitemap_url, nested_sitemap_url)
                    
                    # Recursively fetch nested sitemap
                    try:
                        nested_response = await client.get(nested_sitemap_url, timeout=timeout)
                        nested_response.raise_for_status()
                        nested_content = nested_response.text
                        
                        if nested_content:
                            nested_urls = await _parse_xml_sitemap(nested_content, nested_sitemap_url, client, timeout)
                            urls.update(nested_urls)
                    except Exception as e:
                        logger.warning(f"Error fetching nested sitemap {nested_sitemap_url}: {str(e)}")
                        continue
        
        # Extract URLs from <url><loc> elements (standard sitemap format)
        url_elements = root.findall(".//{*}url")
        if not url_elements:
            # Try without namespace
            url_elements = root.findall(".//url")
        
        for url_elem in url_elements:
            loc_elem = url_elem.find("{*}loc")
            if loc_elem is None:
                # Try without namespace
                loc_elem = url_elem.find("loc")
            
            if loc_elem is not None and loc_elem.text:
                url = loc_elem.text.strip()
                if url:
                    # Resolve relative URLs
                    absolute_url = urljoin(sitemap_url, url)
                    urls.add(absolute_url)
        
        return list(urls)
        
    except ET.ParseError as e:
        logger.warning(f"XML parse error: {str(e)}")
        return []
    except Exception as e:
        logger.warning(f"Error parsing XML sitemap: {str(e)}")
        return []


def _parse_text_sitemap(content: str) -> List[str]:
    """
    Parse text sitemap (one URL per line).
    
    Args:
        content: Text content
        
    Returns:
        List of URLs
    """
    urls = []
    
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):  # Skip empty lines and comments
            # Basic URL validation - check if it looks like a URL
            parsed = urlparse(line)
            if parsed.scheme and parsed.netloc:
                urls.append(line)
    
    return urls


def _is_text_sitemap(content: str) -> bool:
    """
    Check if content appears to be a text sitemap.
    
    Args:
        content: Content to check
        
    Returns:
        True if it looks like a text sitemap
    """
    # Text sitemaps typically have URLs, one per line
    # Check if most lines look like URLs
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
    
    if not lines:
        return False
    
    url_like_count = 0
    for line in lines[:10]:  # Check first 10 non-empty lines
        parsed = urlparse(line)
        if parsed.scheme and parsed.netloc:
            url_like_count += 1
    
    # If at least 50% of lines look like URLs, consider it a text sitemap
    return url_like_count >= max(1, len(lines[:10]) * 0.5)

