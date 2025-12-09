import uuid
from datetime import datetime, timezone
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
from logging_config import get_logger
from services.qdrant_services import get_qdrant_client_instance
from services.elysium_atlas_services.text_chunking_services import chunk_text_content
from services.open_ai_services import get_embeddings
from services.elysium_atlas_services.qdrant_collection_helpers import (
    ensure_agent_knowledge_base_collection_exists,
    AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
    EMBEDDING_DIM,
    EMBEDDING_MODEL
)

logger = get_logger()


async def index_links_in_qdrant(agent_id, fetch_results):
    """
    Index multiple link chunks in Qdrant collection 'agent_knowledge_base' in batch.
    Removes old chunks for the same agent_id and link combinations before indexing new ones.
    Generates embeddings using OpenAI's text-embedding-3-small model and stores chunks with vectors.
    
    Args:
        agent_id: The ID of the agent
        fetch_results: List of fetch result dictionaries, each containing:
            - normalized_url: The normalized URL (required)
            - text_content: The text content to chunk and index (optional, only processes if present)
            - success: Boolean indicating if fetch was successful (optional)
        
    Returns:
        dict: Dictionary with 'total_processed', 'total_chunks', and 'errors' keys
    """
    try:
        # Ensure collection exists (should already be ensured at startup, but this is a safety check)
        await ensure_agent_knowledge_base_collection_exists()
        
        # Filter results to only process those with text_content
        valid_results = []
        for result in fetch_results:
            if result and result.get("text_content") and result.get("normalized_url"):
                valid_results.append({
                    "knowledge_source": result.get("normalized_url"),
                    "text_content": result.get("text_content")
                })
        
        if not valid_results:
            logger.warning(f"No valid results with text_content found for agent_id: {agent_id}")
            return {
                "total_processed": 0,
                "total_chunks": 0,
                "errors": []
            }
        
        logger.info(f"Processing {len(valid_results)} links for agent_id: {agent_id}")
        
        # Get Qdrant client
        client = get_qdrant_client_instance()
        
        # Prepare all points and delete filters
        current_time = datetime.now(timezone.utc).isoformat()
        all_chunks = []  # Store all chunks with metadata for embedding generation
        all_points = []
        delete_filters = []
        total_chunks = 0
        errors = []
        
        # Process each result to chunk text and prepare delete filters
        for result in valid_results:
            knowledge_source = result["knowledge_source"]
            text_content = result["text_content"]
            
            try:
                # Chunk the text content
                chunks = chunk_text_content(text_content)
                
                if not chunks:
                    logger.warning(f"No chunks generated for knowledge_source: {knowledge_source}")
                    continue
                
                logger.debug(f"Generated {len(chunks)} chunks for knowledge_source: {knowledge_source}")
                total_chunks += len(chunks)
                
                # Create delete filter for this knowledge_source
                delete_filter = Filter(
                    must=[
                        FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
                        FieldCondition(key="knowledge_source", match=MatchValue(value=knowledge_source))
                    ]
                )
                delete_filters.append((knowledge_source, delete_filter))
                
                # Store chunks with metadata for later embedding generation
                for index, chunk_text in enumerate(chunks):
                    all_chunks.append({
                        "text_content": chunk_text,
                        "agent_id": agent_id,
                        "knowledge_source": knowledge_source,
                        "text_index": index
                    })
                    
            except Exception as e:
                error_msg = f"Error processing knowledge_source {knowledge_source}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Generate embeddings for all chunks in batch
        if all_chunks:
            try:
                # Extract all chunk texts for embedding generation
                chunk_texts = [chunk["text_content"] for chunk in all_chunks]
                
                # Generate embeddings in batch - vector embeddings of the text_content
                logger.info(f"Generating embeddings for {len(chunk_texts)} chunks using {EMBEDDING_MODEL}")
                embeddings = await get_embeddings(
                    texts=chunk_texts,
                    model=EMBEDDING_MODEL,
                    dimensions=EMBEDDING_DIM
                )
                
                # Create points with embeddings (vector is the embeddings of text_content)
                for chunk_data, embedding in zip(all_chunks, embeddings):
                    point_id = str(uuid.uuid4())
                    
                    point = PointStruct(
                        id=point_id,
                        vector=embedding,  # Vector embeddings of text_content
                        payload={
                            "agent_id": chunk_data["agent_id"],
                            "knowledge_source": chunk_data["knowledge_source"],
                            "text_index": chunk_data["text_index"],
                            "text_content": chunk_data["text_content"],
                            "knowledge_type": "url",
                            "created_at": current_time
                        }
                    )
                    all_points.append(point)
                    
            except Exception as e:
                error_msg = f"Error generating embeddings: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Delete old chunks for all knowledge sources
        for knowledge_source, delete_filter in delete_filters:
            try:
                delete_result = await client.delete(
                    collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                    points_selector=delete_filter
                )
                if delete_result.status == "acknowledged":
                    logger.debug(f"Removed old chunks for agent_id: {agent_id}, knowledge_source: {knowledge_source}")
            except Exception as e:
                error_msg = f"Error deleting old chunks for {knowledge_source}: {e}"
                logger.warning(error_msg)
                errors.append(error_msg)
        
        # Upsert all points in one batch
        if all_points:
            try:
                await client.upsert(
                    collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                    points=all_points
                )
                logger.info(f"Indexed {len(all_points)} chunks in Qdrant collection '{AGENT_KNOWLEDGE_BASE_COLLECTION_NAME}' for agent_id: {agent_id} ({len(valid_results)} knowledge sources)")
            except Exception as e:
                error_msg = f"Error upserting points to Qdrant: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        return {
            "total_processed": len(valid_results),
            "total_chunks": total_chunks,
            "errors": errors
        }

    except Exception as e:
        logger.error(f"Error indexing links in qdrant: {e}")
        return {
            "total_processed": 0,
            "total_chunks": 0,
            "errors": [str(e)]
        }