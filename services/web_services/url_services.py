"""
URL Validator Service - Check if URLs are valid and reachable
"""
import asyncio
import httpx
from typing import Dict, Optional, Any, List
from urllib.parse import urlparse, urljoin, urlunparse
from bs4 import BeautifulSoup, NavigableString

from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError
from logging_config import get_logger
from config.url_filters import (
    FILTERED_SCHEMES,
    FILTERED_DOMAINS,
    FILTER_EMPTY
)

logger = get_logger()


def normalize_url(url: str) -> str:
    """
    Normalize URL by adding scheme if missing and cleaning up the URL
    
    Args:
        url: Raw URL from user
        
    Returns:
        Normalized URL with scheme
        
    Raises:
        ValueError: If URL format is invalid
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    
    url = url.strip()
    
    # Remove common prefixes that users might include
    url = url.removeprefix("www.")
    
    # Check if URL has a scheme
    parsed = urlparse(url)
    
    if not parsed.scheme:
        # No scheme, add https:// by default
        url = f"https://{url}"
        parsed = urlparse(url)
    
    # Validate scheme is http or https
    if parsed.scheme not in ['http', 'https']:
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}. Only http and https are supported.")
    
    # Ensure netloc exists
    if not parsed.netloc:
        raise ValueError("Invalid URL: missing domain/host")
    
    # Reconstruct URL to ensure proper formatting
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc.lower(),  # Lowercase domain
        parsed.path or '/',
        parsed.params,
        parsed.query,
        ''  # Remove fragment
    ))
    
    return normalized


def validate_url_format(url: str) -> bool:
    """
    Basic validation of URL format
    
    Args:
        url: URL to validate
        
    Returns:
        True if format is valid
    """
    try:
        normalized = normalize_url(url)
        parsed = urlparse(normalized)
        return bool(parsed.netloc)
    except:
        return False


async def is_url_reachable(url: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Check if URL is reachable
    
    Args:
        url: URL to check
        timeout: Request timeout in seconds
        
    Returns:
        Dictionary with status and details
    """
    try:
        # Normalize the URL
        normalized_url = normalize_url(url)
        
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                response = await client.head(normalized_url)
                status_code = response.status_code
                
                # If HEAD fails, try GET
                if status_code >= 400:
                    response = await client.get(normalized_url)
                    status_code = response.status_code
                
            except httpx.RequestError:
                # HEAD might not be supported, try GET
                response = await client.get(normalized_url)
                status_code = response.status_code
            
            is_success = 200 <= status_code < 400
            
            return {
                "reachable": is_success,
                "normalized_url": normalized_url,
                "status_code": status_code,
                "final_url": str(response.url),  # In case of redirects
                "error": None
            }
            
    except ValueError as e:
        logger.warning(f"Invalid URL format: {url} - {str(e)}")
        return {
            "reachable": False,
            "url": url,
            "status_code": None,
            "final_url": None,
            "error": str(e)
        }
        
    except httpx.TimeoutException:
        logger.warning(f"Timeout while checking URL: {url}")
        return {
            "reachable": False,
            "url": normalized_url if 'normalized_url' in locals() else url,
            "status_code": None,
            "final_url": None,
            "error": "Request timeout"
        }
        
    except httpx.RequestError as e:
        logger.warning(f"Error checking URL: {url} - {str(e)}")
        return {
            "reachable": False,
            "url": normalized_url if 'normalized_url' in locals() else url,
            "status_code": None,
            "final_url": None,
            "error": f"Request failed: {str(e)}"
        }
        
    except Exception as e:
        logger.error(f"Unexpected error checking URL: {url} - {str(e)}")
        return {
            "reachable": False,
            "url": url,
            "status_code": None,
            "final_url": None,
            "error": f"Unexpected error: {str(e)}"
        }


async def fetch_html_content(
    url: str,
    timeout: int = 30000,
    wait_until: str = "networkidle",
    headless: bool = True
) -> Dict[str, Any]:
    """
    Powerful function that validates, normalizes, and fetches HTML content from a URL using Playwright.
    This function handles JavaScript-rendered content and modern web applications.
    
    Args:
        url: Raw URL from user (will be validated and normalized)
        timeout: Maximum time to wait for page load in milliseconds (default: 30000 = 30 seconds)
        wait_until: When to consider navigation succeeded. Options: 'load', 'domcontentloaded', 'networkidle'
        headless: Whether to run browser in headless mode (default: True)
        
    Returns:
        Dictionary containing:
            - success: bool - Whether the operation was successful
            - url: str - Original URL provided
            - normalized_url: str - Validated and normalized URL
            - final_url: str - Final URL after redirects
            - html_content: str - HTML content of the page (None if failed)
            - title: str - Page title (None if failed)
            - status_code: int - HTTP status code (None if failed)
            - error: str - Error message if failed (None if successful)
    """
    original_url = url
    normalized_url = None
    
    try:
        # Step 1: Validate and normalize the URL
        normalized_url = normalize_url(url)
        logger.info(f"Normalized URL: {original_url} -> {normalized_url}")
        
        # Step 2: Launch Playwright browser and fetch content
        async with async_playwright() as p:
            # Launch Chromium browser
            browser = await p.chromium.launch(headless=headless)
            
            try:
                # Create a new browser context
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                # Create a new page
                page = await context.new_page()
                
                try:
                    # Navigate to the URL
                    response = await page.goto(
                        normalized_url,
                        wait_until=wait_until,
                        timeout=timeout
                    )
                    
                    # Get the final URL (after redirects)
                    final_url = page.url
                    
                    # Get status code
                    status_code = response.status if response else None
                    
                    # Wait for page to be fully loaded (additional wait for dynamic content)
                    await page.wait_for_load_state('networkidle', timeout=5000)
                    
                    # Get HTML content
                    html_content = await page.content()
                    
                    # Get page title
                    title = await page.title()
                    
                    # Check if request was successful
                    is_success = status_code and 200 <= status_code < 400
                    
                    if is_success:
                        logger.info(f"Successfully fetched HTML content from: {normalized_url}")
                        return {
                            "success": True,
                            "url": original_url,
                            "normalized_url": normalized_url,
                            "final_url": final_url,
                            "html_content": html_content,
                            "title": title,
                            "status_code": status_code,
                            "error": None
                        }
                    else:
                        error_msg = f"HTTP {status_code} error"
                        logger.warning(f"Failed to fetch content from {normalized_url}: {error_msg}")
                        return {
                            "success": False,
                            "url": original_url,
                            "normalized_url": normalized_url,
                            "final_url": final_url,
                            "html_content": None,
                            "title": title if title else None,
                            "status_code": status_code,
                            "error": error_msg
                        }
                        
                except PlaywrightTimeoutError as e:
                    logger.warning(f"Timeout while fetching content from: {normalized_url} - {str(e)}")
                    return {
                        "success": False,
                        "url": original_url,
                        "normalized_url": normalized_url,
                        "final_url": None,
                        "html_content": None,
                        "title": None,
                        "status_code": None,
                        "error": f"Request timeout: {str(e)}"
                    }
                    
                except Exception as e:
                    logger.error(f"Error fetching content from {normalized_url}: {str(e)}")
                    return {
                        "success": False,
                        "url": original_url,
                        "normalized_url": normalized_url,
                        "final_url": None,
                        "html_content": None,
                        "title": None,
                        "status_code": None,
                        "error": f"Page navigation error: {str(e)}"
                    }
                    
                finally:
                    await page.close()
                    await context.close()
                    
            finally:
                await browser.close()
                
    except ValueError as e:
        logger.warning(f"Invalid URL format: {original_url} - {str(e)}")
        return {
            "success": False,
            "url": original_url,
            "normalized_url": None,
            "final_url": None,
            "html_content": None,
            "title": None,
            "status_code": None,
            "error": f"Invalid URL format: {str(e)}"
        }
        
    except Exception as e:
        logger.error(f"Unexpected error fetching HTML content from {original_url}: {str(e)}")
        return {
            "success": False,
            "url": original_url,
            "normalized_url": normalized_url if normalized_url else None,
            "final_url": None,
            "html_content": None,
            "title": None,
            "status_code": None,
            "error": f"Unexpected error: {str(e)}"
        }


def extract_text_from_html(html_content: str, base_url: str = None) -> Dict[str, Any]:
    """
    Extract clean text content from HTML using Beautiful Soup.
    Handles UTF-8 encoding safely to prevent encoding errors.
    Includes link URLs in the extracted text for RAG purposes.
    
    Args:
        html_content: HTML content string or bytes to extract text from
        base_url: Base URL to convert relative URLs to absolute URLs (optional)
        
    Returns:
        Dictionary containing:
            - success: bool - Whether the extraction was successful
            - text_content: str - Clean extracted text content (None if failed)
            - text_length: int - Length of extracted text (None if failed)
            - error: str - Error message if failed (None if successful)
    """
    try:
        if not html_content:
            raise ValueError("HTML content must be a non-empty string or bytes")
        
        # Handle bytes input - decode to UTF-8 with error handling
        if isinstance(html_content, bytes):
            try:
                html_content = html_content.decode('utf-8')
            except UnicodeDecodeError:
                # Try with error handling - replace invalid characters
                html_content = html_content.decode('utf-8', errors='replace')
                logger.warning("Encountered invalid UTF-8 characters, replaced with replacement character")
        
        # Ensure we have a string
        if not isinstance(html_content, str):
            raise ValueError("HTML content must be a string or bytes")
        
        # Parse HTML with Beautiful Soup
        # Beautiful Soup automatically detects encoding, but we've ensured UTF-8 input
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script, style, and other non-content elements
        for element in soup(["script", "style", "meta", "link", "noscript", "head"]):
            element.decompose()
        
        # Before extracting text, include link URLs in the text content for RAG purposes
        # Find all anchor tags with href attributes and append the URL to their text
        for anchor_tag in soup.find_all('a', href=True):
            href = anchor_tag.get('href', '').strip()
            
            # If there's a valid href, append it to the link text
            if href:
                # Convert relative URLs to absolute if base_url is provided
                if base_url:
                    try:
                        absolute_href = urljoin(base_url, href).strip()
                        if absolute_href:
                            href = absolute_href
                    except Exception:
                        # If URL joining fails, use the original href
                        pass
                
                # Create a new NavigableString with the URL in brackets
                # This will be appended after the existing content so nested tags are preserved
                url_text = NavigableString(f" [{href}]")
                anchor_tag.append(url_text)
        
        # Get text content
        text_content = soup.get_text(separator=' ', strip=True)
        
        # Ensure text content is UTF-8 encoded string
        if isinstance(text_content, bytes):
            text_content = text_content.decode('utf-8', errors='replace')
        
        # Clean up extra whitespace
        lines = (line.strip() for line in text_content.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text_content = ' '.join(chunk for chunk in chunks if chunk)
        
        # Final UTF-8 validation - ensure we have a valid UTF-8 string
        text_content = text_content.encode('utf-8', errors='replace').decode('utf-8')
        
        logger.info(f"Successfully extracted text content (length: {len(text_content)})")
        
        return {
            "success": True,
            "text_content": text_content,
            "text_length": len(text_content),
            "error": None
        }
        
    except ValueError as e:
        logger.warning(f"Invalid HTML content provided: {str(e)}")
        return {
            "success": False,
            "text_content": None,
            "text_length": None,
            "error": f"Invalid input: {str(e)}"
        }
        
    except Exception as e:
        logger.error(f"Error extracting text from HTML: {str(e)}")
        return {
            "success": False,
            "text_content": None,
            "text_length": None,
            "error": f"Text extraction error: {str(e)}"
        }


def extract_hrefs_from_html(html_content: str, base_url: str = None) -> Dict[str, Any]:
    """
    Extract all href links from HTML content using Beautiful Soup.
    
    Args:
        html_content: HTML content string to extract hrefs from
        base_url: Base URL to convert relative URLs to absolute URLs (optional)
        
    Returns:
        Dictionary containing:
            - success: bool - Whether the extraction was successful
            - hrefs: List[str] - List of extracted href URLs (None if failed)
            - hrefs_count: int - Number of hrefs found (None if failed)
            - error: str - Error message if failed (None if successful)
    """
    try:
        if not html_content or not isinstance(html_content, str):
            raise ValueError("HTML content must be a non-empty string")
        
        # Parse HTML with Beautiful Soup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all elements with href attribute (a, link, area tags)
        hrefs = []
        
        # Extract hrefs from <a> tags
        for tag in soup.find_all('a', href=True):
            href = tag.get('href')
            if href:
                # Strip whitespace from href
                href = href.strip()
                if href:  # Only add if href is not empty after stripping
                    # Convert relative URLs to absolute if base_url is provided
                    if base_url:
                        try:
                            absolute_url = urljoin(base_url, href).strip()
                            if absolute_url:
                                hrefs.append(absolute_url)
                        except Exception:
                            if href:
                                hrefs.append(href)
                    else:
                        hrefs.append(href)
        
        # Extract hrefs from <link> tags (CSS, favicons, etc.)
        for tag in soup.find_all('link', href=True):
            href = tag.get('href')
            if href:
                # Strip whitespace from href
                href = href.strip()
                if href:  # Only add if href is not empty after stripping
                    if base_url:
                        try:
                            absolute_url = urljoin(base_url, href).strip()
                            if absolute_url:
                                hrefs.append(absolute_url)
                        except Exception:
                            if href:
                                hrefs.append(href)
                    else:
                        hrefs.append(href)
        
        # Extract hrefs from <area> tags (image maps)
        for tag in soup.find_all('area', href=True):
            href = tag.get('href')
            if href:
                # Strip whitespace from href
                href = href.strip()
                if href:  # Only add if href is not empty after stripping
                    if base_url:
                        try:
                            absolute_url = urljoin(base_url, href).strip()
                            if absolute_url:
                                hrefs.append(absolute_url)
                        except Exception:
                            if href:
                                hrefs.append(href)
                    else:
                        hrefs.append(href)
        
        # Remove duplicates while preserving order and strip any remaining whitespace
        unique_hrefs = []
        seen = set()
        for href in hrefs:
            # Final strip to ensure no whitespace
            href = href.strip() if isinstance(href, str) else href
            if href and href not in seen:
                seen.add(href)
                unique_hrefs.append(href)
        
        logger.info(f"Successfully extracted {len(unique_hrefs)} unique hrefs from HTML content")
        
        return {
            "success": True,
            "hrefs": unique_hrefs,
            "hrefs_count": len(unique_hrefs),
            "error": None
        }
        
    except ValueError as e:
        logger.warning(f"Invalid HTML content provided for href extraction: {str(e)}")
        return {
            "success": False,
            "hrefs": None,
            "hrefs_count": None,
            "error": f"Invalid input: {str(e)}"
        }
        
    except Exception as e:
        logger.error(f"Error extracting hrefs from HTML: {str(e)}")
        return {
            "success": False,
            "hrefs": None,
            "hrefs_count": None,
            "error": f"Href extraction error: {str(e)}"
        }


def filter_urls(urls: List[str]) -> List[str]:
    """
    Filter out invalid and unnecessary URLs from a list.
    Removes URLs with filtered schemes, domains, and patterns.
    
    Args:
        urls: List of URLs to filter
        
    Returns:
        Filtered list of URLs with invalid/unnecessary links removed
    """
    if not urls or not isinstance(urls, list):
        return []
    
    filtered_urls = []
    
    for url in urls:
        if not url or not isinstance(url, str):
            continue
        
        url = url.strip()
        
        # Filter empty URLs
        if FILTER_EMPTY and not url:
            continue
        
        # Parse URL to check scheme and domain
        try:
            parsed = urlparse(url)
            
            # Filter by scheme
            if parsed.scheme and parsed.scheme.lower() in FILTERED_SCHEMES:
                continue
            
            # Filter by domain
            if parsed.netloc:
                domain = parsed.netloc.lower()
                # Remove www. prefix for comparison
                domain_clean = domain.removeprefix("www.")
                
                # Check if domain matches any filtered domain
                if any(filtered_domain in domain_clean for filtered_domain in FILTERED_DOMAINS):
                    continue
            
            # If URL passed all filters, add it
            filtered_urls.append(url)
            
        except Exception as e:
            # If URL parsing fails, skip it
            logger.debug(f"Skipping invalid URL during filtering: {url} - {str(e)}")
            continue
    
    logger.info(f"Filtered {len(urls)} URLs to {len(filtered_urls)} valid URLs")
    return filtered_urls


async def _process_single_url(
    url: str,
    semaphore: asyncio.Semaphore,
    timeout: int,
    wait_until: str,
    headless: bool
) -> Dict[str, Any]:
    """
    Helper function to process a single URL with semaphore-controlled concurrency.
    
    Args:
        url: URL to process
        semaphore: Asyncio semaphore to limit concurrent executions
        timeout: Maximum time to wait for page load in milliseconds
        wait_until: When to consider navigation succeeded
        headless: Whether to run browser in headless mode
        
    Returns:
        Dictionary with processing results
    """
    async with semaphore:
        if not url or not isinstance(url, str):
            logger.warning(f"Skipping invalid URL entry: {url}")
            return {
                "success": False,
                "url": str(url) if url else None,
                "normalized_url": None,
                "final_url": None,
                "html_content": None,
                "text_content": None,
                "text_length": None,
                "hrefs": None,
                "hrefs_count": None,
                "title": None,
                "status_code": None,
                "error": "Invalid URL: must be a non-empty string"
            }
        
        try:
            # Step 1: Validate and normalize URL
            normalized_url = normalize_url(url)
            logger.info(f"Processing URL: {url} -> {normalized_url}")
            
            # Step 2: Fetch HTML content using existing function
            html_result = await fetch_html_content(
                url=url,
                timeout=timeout,
                wait_until=wait_until,
                headless=headless
            )
            
            # Step 3: Extract text content and hrefs if HTML was successfully fetched
            text_content = None
            text_length = None
            hrefs = None
            hrefs_count = None
            
            if html_result.get("success") and html_result.get("html_content"):
                html_content = html_result.get("html_content")
                final_url = html_result.get("final_url") or html_result.get("normalized_url")
                
                # Extract text content (include links in text for RAG purposes)
                text_result = extract_text_from_html(html_content, base_url=final_url)
                if text_result.get("success"):
                    text_content = text_result.get("text_content")
                    text_length = text_result.get("text_length")
                
                # Extract hrefs using final_url as base for absolute URL conversion
                hrefs_result = extract_hrefs_from_html(html_content, base_url=final_url)
                if hrefs_result.get("success"):
                    hrefs = hrefs_result.get("hrefs")
                    
                    # Ensure the normalized URL (with trailing slash) is the first element
                    normalized_url_for_href = html_result.get("normalized_url")
                    if normalized_url_for_href:
                        # Ensure normalized URL ends with '/' for the base URL
                        if not normalized_url_for_href.endswith('/'):
                            # Parse and reconstruct with trailing slash
                            parsed = urlparse(normalized_url_for_href)
                            normalized_url_for_href = urlunparse((
                                parsed.scheme,
                                parsed.netloc,
                                parsed.path.rstrip('/') + '/' if parsed.path != '/' else '/',
                                parsed.params,
                                parsed.query,
                                ''  # Remove fragment
                            ))
                        
                        # Prepend normalized URL as first element if not already present
                        if normalized_url_for_href not in hrefs:
                            hrefs.insert(0, normalized_url_for_href)
                        else:
                            # If it exists, move it to the first position
                            hrefs.remove(normalized_url_for_href)
                            hrefs.insert(0, normalized_url_for_href)
                    
                    # Remove any duplicate URLs while preserving order (normalized URL should remain first)
                    seen = set()
                    unique_hrefs = []
                    for href in hrefs:
                        if href and href not in seen:
                            seen.add(href)
                            unique_hrefs.append(href)
                    
                    hrefs = unique_hrefs
                    hrefs_count = len(hrefs)
            
            # Step 4: Build result dictionary
            result = {
                "success": html_result.get("success", False),
                "url": url,
                "normalized_url": html_result.get("normalized_url"),
                "final_url": html_result.get("final_url"),
                # "html_content": html_result.get("html_content"),
                "text_content": text_content,
                "text_length": text_length,
                "hrefs": hrefs,
                "hrefs_count": hrefs_count,
                "title": html_result.get("title"),
                "status_code": html_result.get("status_code"),
                "error": html_result.get("error")
            }
            
            if result["success"]:
                logger.info(f"Successfully processed URL: {url}")
            else:
                logger.warning(f"Failed to process URL: {url} - {html_result.get('error')}")
            
            return result
                
        except ValueError as e:
            # URL validation/normalization failed
            logger.warning(f"URL validation failed for {url}: {str(e)}")
            return {
                "success": False,
                "url": url,
                "normalized_url": None,
                "final_url": None,
                "html_content": None,
                "text_content": None,
                "text_length": None,
                "hrefs": None,
                "hrefs_count": None,
                "title": None,
                "status_code": None,
                "error": f"URL validation error: {str(e)}"
            }
            
        except Exception as e:
            # Unexpected error
            logger.error(f"Unexpected error processing URL {url}: {str(e)}")
            return {
                "success": False,
                "url": url,
                "normalized_url": None,
                "final_url": None,
                "html_content": None,
                "text_content": None,
                "text_length": None,
                "hrefs": None,
                "hrefs_count": None,
                "title": None,
                "status_code": None,
                "error": f"Unexpected error: {str(e)}"
            }


async def fetch_multiple_urls_content(
    urls: List[str], 
    timeout: int = 60000, 
    wait_until: str = "networkidle", 
    headless: bool = True,
    batch_size: int = 5
) -> List[Dict[str, Any]]:
    """
    Process multiple URLs: validate, normalize, fetch HTML content, and extract text.
    This is a comprehensive service function that handles the complete workflow for multiple URLs.
    Processes URLs in batches with controlled concurrency to manage memory usage.
    
    Args:
        urls: List of URLs to process
        timeout: Maximum time to wait for page load in milliseconds (default: 60000 = 60 seconds)
        wait_until: When to consider navigation succeeded. Options: 'load', 'domcontentloaded', 'networkidle'
        headless: Whether to run browser in headless mode (default: True)
        batch_size: Number of URLs to process concurrently (default: 5, suitable for 2GB RAM machines)
        
    Returns:
        List of dictionaries, each containing:
            - success: bool - Whether the operation was successful
            - url: str - Original URL provided
            - normalized_url: str - Validated and normalized URL (None if validation failed)
            - final_url: str - Final URL after redirects (None if failed)
            - html_content: str - HTML content of the page (None if failed)
            - text_content: str - Clean extracted text content (None if failed or HTML unavailable)
            - text_length: int - Length of extracted text (None if failed)
            - hrefs: List[str] - List of all href links found in the HTML (None if failed or HTML unavailable)
            - hrefs_count: int - Number of unique hrefs found (None if failed)
            - title: str - Page title (None if failed)
            - status_code: int - HTTP status code (None if failed)
            - error: str - Error message if failed (None if successful)
    """
    if not urls or not isinstance(urls, list):
        logger.warning("Invalid URLs input: must be a non-empty list")
        return []
    
    # Validate batch_size
    if batch_size < 1:
        logger.warning(f"Invalid batch_size {batch_size}, using default value of 5")
        batch_size = 5
    elif batch_size > 10:
        logger.warning(f"batch_size {batch_size} is high for 2GB RAM machines, consider using 5-7")
    
    logger.info(f"Processing {len(urls)} URLs in batches of {batch_size} concurrent requests")
    
    # Create semaphore to limit concurrent executions
    semaphore = asyncio.Semaphore(batch_size)
    
    # Create tasks for all URLs
    tasks = [
        _process_single_url(url, semaphore, timeout, wait_until, headless)
        for url in urls
    ]
    
    # Execute all tasks concurrently (limited by semaphore)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Handle any exceptions that weren't caught in the task
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Unexpected exception processing URL {urls[i]}: {str(result)}")
            processed_results.append({
                "success": False,
                "url": urls[i] if i < len(urls) else None,
                "normalized_url": None,
                "final_url": None,
                "html_content": None,
                "text_content": None,
                "text_length": None,
                "hrefs": None,
                "hrefs_count": None,
                "title": None,
                "status_code": None,
                "error": f"Task exception: {str(result)}"
            })
        else:
            processed_results.append(result)
    
    success_count = sum(1 for r in processed_results if r.get('success'))
    failed_count = len(processed_results) - success_count
    logger.info(f"Completed processing {len(urls)} URLs. Success: {success_count}, Failed: {failed_count}")
    
    return processed_results