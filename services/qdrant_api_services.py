from logging_config import get_logger
import httpx
from config.settings import settings

logger = get_logger()

async def search_qdrant_collection(collection_name: str, vector: list, filters: dict = None, limit: int = 10, with_payload: bool = True):
    """
    Search for similar points in a Qdrant collection using vector similarity.
    
    Args:
        collection_name (str): Name of the Qdrant collection to search
        vector (list): Query vector for semantic search
        filters (dict): Optional filters to apply to the search (Qdrant filter format)
        limit (int): Maximum number of results to return (default: 10)
        with_payload (bool): Whether to include payload in results (default: True)
    
    Returns:
        list: List of search results, or empty list if error
    """
    try:
        # Construct the search URL
        url = f"{settings.QDRANT_CLUSTER_ENDPOINT}/collections/{collection_name}/points/search"
        
        # Build the request payload
        payload = {
            "vector": vector,
            "limit": limit,
            "with_payload": with_payload
        }
        
        # Add filters if provided
        if filters:
            payload["filter"] = filters
        
        # Headers for authentication
        headers = {
            "Content-Type": "application/json"
        }
        
        if settings.QDRANT_API_KEY:
            headers["Authorization"] = f"Bearer {settings.QDRANT_API_KEY}"
        
        # Make the API request
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            
            result = response.json()
            search_results = result.get("result", [])
            
            logger.info(f"Found {len(search_results)} results in collection '{collection_name}'")
            return search_results
        
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error searching collection '{collection_name}': {e.response.status_code} - {e.response.text}")
        return []
    except Exception as e:
        logger.error(f"Error searching collection '{collection_name}': {e}")
        return []


async def delete_qdrant_points_by_filter(collection_name: str, filters: dict):
    """
    Delete all points in a Qdrant collection that match the given filters.
    
    Args:
        collection_name (str): Name of the Qdrant collection
        filters (dict): Filters to identify points to delete (Qdrant filter format)
    
    Returns:
        dict: Dictionary with 'success' (bool) and 'message' (str) keys
    """
    try:
        # Construct the delete URL
        url = f"{settings.QDRANT_CLUSTER_ENDPOINT}/collections/{collection_name}/points/delete"
        
        # Build the request payload
        payload = {
            "filter": filters
        }
        
        # Headers for authentication
        headers = {
            "Content-Type": "application/json"
        }
        
        if settings.QDRANT_API_KEY:
            headers["Authorization"] = f"Bearer {settings.QDRANT_API_KEY}"
        
        # Make the API request
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            
            result = response.json()
            
            logger.info(f"Successfully deleted points from collection '{collection_name}' with filters: {filters}")
            return {
                "success": True,
                "message": f"Points deleted successfully from collection '{collection_name}'",
                "result": result
            }
        
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error deleting points from collection '{collection_name}': {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return {
            "success": False,
            "message": error_msg
        }
    except Exception as e:
        error_msg = f"Error deleting points from collection '{collection_name}': {e}"
        logger.error(error_msg)
        return {
            "success": False,
            "message": error_msg
        }