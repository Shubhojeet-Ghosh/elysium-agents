from typing import List, Dict, Any
from logging_config import get_logger
from config.atlas_metadata_extraction_models import AgentWebCatalogEntry
from services.open_ai_services import openai_structured_output

logger = get_logger()


async def extract_metadata_from_fetch_results(fetch_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract metadata from fetch_results using OpenAI structured output.
    Adds/updates the 'metadata' key in each fetch_result object.
    
    Args:
        fetch_results: List of dictionaries containing URL fetch results with structure:
            - success: bool
            - url: str
            - normalized_url: str (optional)
            - text_content: str (optional)
            - error: str (optional)
    
    Returns:
        List[Dict[str, Any]]: Updated fetch_results list with 'metadata' key added to each object
    """
    logger.info(f"Processing {len(fetch_results)} fetch results for metadata extraction")
    
    updated_results = []
    model = "gpt-4.1-nano"
    
    for result in fetch_results:
        # Skip if fetch was not successful or no text_content available
        if not result.get("success") or not result.get("text_content"):
            logger.debug(f"Skipping metadata extraction for {result.get('url', 'unknown')} - no text content")
            result["metadata"] = None
            updated_results.append(result)
            continue
        
        # Get the URL to use (prefer normalized_url, fallback to url)
        url = result.get("normalized_url") or result.get("url", "")
        text_content = result.get("text_content", "")
        
        try:
            # Build messages for metadata extraction
            messages = [
                {
                    "role": "system",
                    "content": "You are an expert at extracting structured metadata from web page content. Analyze the provided text and extract key information including page type, summary, and product-specific details if applicable."
                },
                {
                    "role": "user",
                    "content": f"Extract structured metadata from the following web page content. URL: {url}\n\nContent:\n{text_content}"
                }
            ]
            
            logger.debug(f"Extracting metadata for URL: {url}")
            
            # Call OpenAI structured output
            metadata = await openai_structured_output(
                model=model,
                messages=messages,
                response_format=AgentWebCatalogEntry
            )
            
            # Ensure the URL in metadata matches the normalized URL
            metadata["url"] = url
            
            # Add metadata to the result
            result["metadata"] = metadata
            logger.debug(f"Successfully extracted metadata for {url}")
            
        except Exception as e:
            logger.warning(f"Error extracting metadata for {url}: {e}")
            result["metadata"] = None
        
        updated_results.append(result)
    
    successful_extractions = sum(1 for r in updated_results if r.get("metadata") is not None)
    logger.info(f"Metadata extraction completed: {successful_extractions}/{len(fetch_results)} successful")
    
    return updated_results

