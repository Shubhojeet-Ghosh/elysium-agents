from typing import List
from datetime import datetime, timezone

from logging_config import get_logger
from services.mongo_services import get_collection
from services.web_services.url_services import fetch_multiple_urls_content
from services.elysium_atlas_services.atlas_qdrant_services import index_links_in_qdrant
from pymongo import UpdateOne

logger = get_logger()

async def index_agent_urls(agent_id: str, links: List[str], batch_size: int = 5) -> bool:
    """
    Index the links for an agent and store each link as an individual document in MongoDB.
    Processes links in batches for improved performance.
    
    Args:
        agent_id: The ID of the agent
        links: List of URLs to index
        batch_size: Number of URLs to process in each batch (default: 5)
        
    Returns:
        bool: True if links were stored successfully, False otherwise
    """
    try:
        
        # Validate links exist, is a list, has length > 0, and each link is truthy
        if not links:
            logger.warning("No links found")
            return False
        
        if len(links) == 0:
            logger.warning("Links list is empty")
            return False
        
        # Filter out non-truthy links
        valid_links = [link for link in links if link]
        
        if len(valid_links) == 0:
            logger.warning("No valid (truthy) links found in the list")
            return False
        
        # Validate batch_size
        if batch_size < 1:
            logger.warning(f"Invalid batch_size {batch_size}, using default value of 5")
            batch_size = 5
        
        # Get the collection
        collection = get_collection("atlas_agent_urls")
        
        total_links = len(valid_links)
        logger.info(f"Processing {total_links} links in batches of {batch_size}")
        
        # Process links in batches
        total_inserted = 0
        current_time = datetime.now(timezone.utc)
        
        # Split links into batches
        for batch_start in range(0, total_links, batch_size):
            batch_end = min(batch_start + batch_size, total_links)
            batch_links = valid_links[batch_start:batch_end]
            batch_number = (batch_start // batch_size) + 1
            total_batches = (total_links + batch_size - 1) // batch_size
            
            logger.info(f"Processing batch {batch_number}/{total_batches} ({len(batch_links)} URLs)")
            
            # Fetch content for all URLs in this batch
            fetch_results = []
            try:
                # Call fetch_multiple_urls_content with batch of URLs
                fetch_results = await fetch_multiple_urls_content(batch_links, batch_size=batch_size)
            except Exception as fetch_error:
                logger.warning(f"Error fetching content for batch {batch_number}: {fetch_error}")
                # Create error results for all URLs in this batch
                fetch_results = [
                    {
                        "success": False,
                        "url": link,
                        "normalized_url": None,
                        "text_content": None,
                        "error": f"Batch fetch error: {str(fetch_error)}"
                    }
                    for link in batch_links
                ]
            
            # Process all results in batch for Qdrant indexing
            try:
                qdrant_result = await index_links_in_qdrant(agent_id, fetch_results)
                if qdrant_result.get("errors"):
                    for error in qdrant_result["errors"]:
                        logger.warning(f"Qdrant indexing error: {error}")
                logger.info(f"Qdrant indexing: {qdrant_result.get('total_processed', 0)} links processed, {qdrant_result.get('total_chunks', 0)} chunks indexed")
            except Exception as qdrant_error:
                logger.warning(f"Error indexing batch in Qdrant: {qdrant_error}")
            
            # Prepare bulk operations for MongoDB
            bulk_operations = []
            for result in fetch_results:
                # Determine the link to use (prefer normalized_url, fallback to url)
                link = result.get("normalized_url") or result.get("url")
                if not link:
                    continue
                
                # Prepare update document - text_content is stored in Qdrant, not MongoDB
                update_doc = {
                    "$set": {
                        "updated_at": current_time,
                        "status": "indexing"
                    },
                    "$setOnInsert": {
                        "agent_id": agent_id,
                        "url": link,
                        "created_at": current_time
                    }
                }
                
                # Create UpdateOne operation for bulk write
                bulk_operations.append(
                    UpdateOne(
                        {"agent_id": agent_id, "url": link},
                        update_doc,
                        upsert=True
                    )
                )
            
            # Execute bulk write for MongoDB
            if bulk_operations:
                try:
                    bulk_result = await collection.bulk_write(bulk_operations, ordered=False)
                    total_inserted += bulk_result.upserted_count + bulk_result.modified_count
                    logger.info(f"MongoDB bulk write: {bulk_result.upserted_count} inserted, {bulk_result.modified_count} updated")
                except Exception as bulk_error:
                    logger.warning(f"Error in MongoDB bulk write: {bulk_error}. Continuing...")
            
            # Log progress after each batch
            logger.info(f"Progress: Processed {min(batch_end, total_links)}/{total_links} links ({total_inserted} inserted/updated)")
        
        logger.info(f"Completed processing links: {total_inserted}/{total_links} links processed (inserted/updated) in atlas_agent_urls collection")
        return total_inserted > 0
        
    except Exception as e:
        logger.error(f"Error storing agent URLs: {e}")
        return False

