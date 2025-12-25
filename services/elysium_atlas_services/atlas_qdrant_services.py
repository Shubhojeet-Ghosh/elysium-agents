import uuid
from typing import List, Dict, Any
from datetime import datetime, timezone
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
from logging_config import get_logger
from services.qdrant_services import get_qdrant_client_instance
from services.elysium_atlas_services.text_chunking_services import chunk_text_content
from services.open_ai_services import get_embeddings
from services.elysium_atlas_services.qdrant_collection_helpers import (
    ensure_agent_knowledge_base_collection_exists,
    ensure_agent_web_catalog_collection_exists,
    AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
    AGENT_WEB_CATALOG_COLLECTION_NAME,
    EMBEDDING_DIM,
    EMBEDDING_MODEL
)


async def remove_all_qdrant_agent_points(agent_id: str) -> dict:
    """
    Remove all points for the given agent_id from both Qdrant collections:
    - agent_knowledge_base
    - agent_web_catalog

    Args:
        agent_id (str): The ID of the agent whose points should be removed.

    Returns:
        dict: Dictionary with 'knowledge_base_deleted', 'web_catalog_deleted', and 'errors' keys.
    """
    errors = []
    knowledge_base_deleted = 0
    web_catalog_deleted = 0
    try:
        await ensure_agent_knowledge_base_collection_exists()
        await ensure_agent_web_catalog_collection_exists()
        client = get_qdrant_client_instance()

        # Delete from agent_knowledge_base
        try:
            kb_filter = Filter(must=[FieldCondition(key="agent_id", match=MatchValue(value=agent_id))])
            kb_result = await client.delete(
                collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                points_selector=kb_filter
            )
            if hasattr(kb_result, "status") and kb_result.status == "acknowledged":
                logger.info(f"Deleted all points for agent_id={agent_id} from {AGENT_KNOWLEDGE_BASE_COLLECTION_NAME}")
            knowledge_base_deleted = getattr(kb_result, "deleted", 0) if hasattr(kb_result, "deleted") else 0
        except Exception as e:
            error_msg = f"Error deleting from knowledge base: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

        # Delete from agent_web_catalog
        try:
            wc_filter = Filter(must=[FieldCondition(key="agent_id", match=MatchValue(value=agent_id))])
            wc_result = await client.delete(
                collection_name=AGENT_WEB_CATALOG_COLLECTION_NAME,
                points_selector=wc_filter
            )
            if hasattr(wc_result, "status") and wc_result.status == "acknowledged":
                logger.info(f"Deleted all points for agent_id={agent_id} from {AGENT_WEB_CATALOG_COLLECTION_NAME}")
            web_catalog_deleted = getattr(wc_result, "deleted", 0) if hasattr(wc_result, "deleted") else 0
        except Exception as e:
            error_msg = f"Error deleting from web catalog: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

        return {
            "knowledge_base_deleted": knowledge_base_deleted,
            "web_catalog_deleted": web_catalog_deleted,
            "errors": errors
        }
    except Exception as e:
        logger.error(f"Error removing all agent points: {e}")
        return {
            "knowledge_base_deleted": 0,
            "web_catalog_deleted": 0,
            "errors": [str(e)]
        }

logger = get_logger()


async def index_links_in_knowledge_base(agent_id, metadata_results):
    """
    Index multiple link chunks in Qdrant collection 'agent_knowledge_base' in batch.
    Removes old chunks for the same agent_id and link combinations before indexing new ones.
    Generates embeddings using OpenAI's text-embedding-3-small model and stores chunks with vectors.

    Args:
        agent_id: The ID of the agent
        metadata_results: List of metadata result dictionaries, each containing:
            - normalized_url: The normalized URL (required)
            - text_content: The text content to chunk and index (optional, only processes if present)
            - metadata: Dict containing additional metadata (e.g., "page_type")

    Returns:
        dict: Dictionary with 'total_processed', 'total_chunks', and 'errors' keys
    """
    try:
        # Ensure collection exists (should already be ensured at startup, but this is a safety check)
        await ensure_agent_knowledge_base_collection_exists()

        # Filter results to only process those with text_content
        valid_results = []
        for result in metadata_results:
            if result and result.get("text_content") and result.get("normalized_url"):
                metadata = result.get("metadata", {})
                valid_results.append({
                    "knowledge_source": result.get("normalized_url"),
                    "text_content": result.get("text_content"),
                    "page_type": metadata.get("page_type", "unknown")  # Default to "unknown" if not provided
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
            page_type = result["page_type"]

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
                        "text_index": index,
                        "page_type": page_type
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
                            "page_type": chunk_data["page_type"],
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


async def index_metadata_in_web_catalog(agent_id: str, metadata_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Index metadata results into Qdrant collection 'agent_web_catalog'.
    Stores structured metadata (page_type, summary, url, product info, etc.) for agent routing.
    Generates embeddings from the summary field for semantic search.

    Args:
        agent_id: The ID of the agent
        metadata_results: List of metadata result dictionaries, each containing:
            - metadata: Dict with structured metadata (AgentWebCatalogEntry format)
            - normalized_url: The normalized URL (required)
            - success: Boolean indicating if fetch was successful (optional)

    Returns:
        dict: Dictionary with 'total_processed', 'total_indexed', and 'errors' keys
    """
    try:
        # Ensure collection exists
        await ensure_agent_web_catalog_collection_exists()

        # Filter results to only process those with valid metadata
        valid_results = []
        for result in metadata_results:
            if result and result.get("metadata") and result.get("normalized_url"):
                metadata = result.get("metadata")
                # Ensure metadata has required fields
                if metadata.get("url") and metadata.get("summary"):
                    valid_results.append(result)

        if not valid_results:
            logger.warning(f"No valid metadata results found for agent_id: {agent_id}")
            return {
                "total_processed": 0,
                "total_indexed": 0,
                "errors": []
            }

        logger.info(f"Processing {len(valid_results)} metadata results for agent_id: {agent_id}")

        # Get Qdrant client
        client = get_qdrant_client_instance()

        # Prepare all points
        current_time = datetime.now(timezone.utc).isoformat()
        all_points = []
        results_with_summaries = []  # Track results that have valid summaries
        summaries = []
        urls_to_update = []  # Track URLs that will be updated
        errors = []

        # Process each result to prepare summaries (NO CHUNKING - one summary per result)
        for result in valid_results:
            metadata = result.get("metadata")
            url = result.get("normalized_url") or metadata.get("url", "")

            try:
                # Extract summary for embedding generation (NO CHUNKING - single summary per metadata result)
                summary = metadata.get("summary", "")
                if not summary:
                    logger.warning(f"No summary found for URL: {url}")
                    continue

                # Store both result and summary to maintain 1:1 mapping
                summaries.append(summary)
                results_with_summaries.append(result)
                urls_to_update.append(url)

            except Exception as e:
                error_msg = f"Error processing metadata for {url}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        # Delete old points with the same URLs (to ensure uniqueness - one point per URL per agent)
        if urls_to_update:
            try:
                for url in urls_to_update:
                    # Create filter to delete points with same agent_id and url
                    delete_filter = Filter(
                        must=[
                            FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
                            FieldCondition(key="url", match=MatchValue(value=url))
                        ]
                    )
                    try:
                        delete_result = await client.delete(
                            collection_name=AGENT_WEB_CATALOG_COLLECTION_NAME,
                            points_selector=delete_filter
                        )
                        if delete_result.status == "acknowledged":
                            logger.debug(f"Removed old point for agent_id: {agent_id}, url: {url}")
                    except Exception as e:
                        # Ignore errors if point doesn't exist (first time indexing)
                        logger.debug(f"Could not delete old point for {url} (may not exist): {e}")
            except Exception as e:
                error_msg = f"Error deleting old points: {e}"
                logger.warning(error_msg)
                # Continue processing even if deletion fails

        # Generate embeddings for all summaries in batch (NO CHUNKING - one embedding per summary)
        if summaries:
            try:
                logger.info(f"Generating embeddings for {len(summaries)} summaries using {EMBEDDING_MODEL}")
                embeddings = await get_embeddings(
                    texts=summaries,
                    model=EMBEDDING_MODEL,
                    dimensions=EMBEDDING_DIM
                )

                # Create ONE point per metadata result (NO CHUNKING - 1:1 mapping)
                for result, embedding, url in zip(results_with_summaries, embeddings, urls_to_update):
                    metadata = result.get("metadata")

                    # Generate deterministic UUID5 based on agent_id + url (same URL always gets same point_id)
                    composite_key = f"{agent_id}:{url}"
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, composite_key))

                    # Each metadata result becomes exactly ONE point in Qdrant
                    # Point ID is deterministic, so same URL will always have same ID

                    point = PointStruct(
                        id=point_id,
                        vector=embedding,  # Vector embeddings of summary (one embedding per result)
                        payload={
                            "agent_id": agent_id,
                            "knowledge_source": metadata.get("url"),
                            "page_type": metadata.get("page_type"),
                            "summary": metadata.get("summary"),
                            "product_name": metadata.get("product_name"),
                            "product_id": metadata.get("product_id"),
                            "category": metadata.get("category"),
                            "price": metadata.get("price"),
                            "currency": metadata.get("currency"),
                            "is_available": metadata.get("is_available"),
                            "created_at": current_time,
                            "knowledge_type": "url"
                        }
                    )
                    all_points.append(point)

            except Exception as e:
                error_msg = f"Error generating embeddings: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        # Upsert all points in one batch (upsert will update if point_id exists, insert if new)
        if all_points:
            try:
                await client.upsert(
                    collection_name=AGENT_WEB_CATALOG_COLLECTION_NAME,
                    points=all_points
                )
                logger.info(f"Indexed {len(all_points)} metadata entries in Qdrant collection '{AGENT_WEB_CATALOG_COLLECTION_NAME}' for agent_id: {agent_id}")
            except Exception as e:
                error_msg = f"Error upserting points to Qdrant: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        return {
            "total_processed": len(valid_results),
            "total_indexed": len(all_points),
            "errors": errors
        }

    except Exception as e:
        logger.error(f"Error indexing metadata in web catalog: {e}")
        return {
            "total_processed": 0,
            "total_indexed": 0,
            "errors": [str(e)]
        }