from logging_config import get_logger
import asyncio
from services.qdrant_api_services import search_qdrant_collection
from services.open_ai_services import get_embeddings
from services.elysium_atlas_services.qdrant_collection_helpers import (
    AGENT_WEB_CATALOG_COLLECTION_NAME,
    AGENT_KNOWLEDGE_BASE_COLLECTION_NAME
)

logger = get_logger()

# Qdrant search configuration
QDRANT_WEB_CATALOG_LIMIT = 10
QDRANT_SOURCE_BASED_KNOWLEDGE_LIMIT = 15
QDRANT_DIRECT_KNOWLEDGE_LIMIT = 15

async def search_agent_web_catalog(agent_id: str, vector: list, limit: int = 10):
    """
    Search for the top k similar points in the agent_web_catalog collection using Qdrant API.
    
    Args:
        agent_id (str): The ID of the agent to filter results for
        vector (list): The query vector for semantic search
        limit (int): Maximum number of results to return (default: 10)
    
    Returns:
        list: List of search results with payloads
    """
    try:
        # Build filters for agent_id
        filters = {
            "must": [
                {
                    "key": "agent_id",
                    "match": {
                        "value": agent_id
                    }
                }
            ]
        }
        
        # Call the Qdrant search service
        search_results = await search_qdrant_collection(
            collection_name=AGENT_WEB_CATALOG_COLLECTION_NAME,
            vector=vector,
            filters=filters,
            limit=limit,
            with_payload=True
        )
        
        logger.info(f"Found {len(search_results)} results for agent_id: {agent_id}")
        return search_results
        
    except Exception as e:
        logger.error(f"Error searching agent web catalog for agent_id {agent_id}: {e}")
        return []


async def search_agent_knowledge_base(agent_id: str, vector: list, knowledge_source: str = None, knowledge_sources: list = None, limit: int = 10):
    """
    Search for the top k similar points in the agent_knowledge_base collection using Qdrant API.
    
    Args:
        agent_id (str): The ID of the agent to filter results for
        vector (list): The query vector for semantic search
        knowledge_source (str): Optional single knowledge_source to filter by (e.g., URL or file name)
        knowledge_sources (list): Optional list of knowledge_sources to filter by (matches any)
        limit (int): Maximum number of results to return (default: 10)
    
    Returns:
        list: List of search results with payloads
    """
    try:
        # Build filters for agent_id
        must_conditions = [
            {
                "key": "agent_id",
                "match": {
                    "value": agent_id
                }
            }
        ]
        
        # Add knowledge_source filter if provided (single value)
        if knowledge_source:
            must_conditions.append({
                "key": "knowledge_source",
                "match": {
                    "value": knowledge_source
                }
            })
        # Add knowledge_sources filter if provided (multiple values - match any)
        elif knowledge_sources and isinstance(knowledge_sources, list) and len(knowledge_sources) > 0:
            must_conditions.append({
                "key": "knowledge_source",
                "match": {
                    "any": knowledge_sources
                }
            })
        
        filters = {"must": must_conditions}
        
        # Call the Qdrant search service
        search_results = await search_qdrant_collection(
            collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
            vector=vector,
            filters=filters,
            limit=limit,
            with_payload=True
        )
        
        logger.info(f"Found {len(search_results)} knowledge base results for agent_id: {agent_id}" + 
                   (f", knowledge_source: {knowledge_source}" if knowledge_source else "") +
                   (f", knowledge_sources count: {len(knowledge_sources)}" if knowledge_sources else ""))
        return search_results
        
    except Exception as e:
        logger.error(f"Error searching agent knowledge base for agent_id {agent_id}: {e}")
        return []


async def search_and_merge_agent_knowledge(agent_id: str, message: str):
    """
    Comprehensive search and merge function for agent knowledge.
    Searches both web catalog and knowledge base, merges results by knowledge_source,
    and returns sorted results by relevance score.
    
    Args:
        agent_id (str): The ID of the agent
        message (str): The user's message to search for
    
    Returns:
        list: Final merged and sorted results by knowledge_source
    """
    try:
        # Generate embedding for the message
        embeddings = await get_embeddings([message])
        embedding = embeddings[0]
        
        # Step 1: Search the agent web catalog for relevant information
        catalog_results = await search_agent_web_catalog(agent_id, embedding, limit=QDRANT_WEB_CATALOG_LIMIT)
        
        # Extract payloads from catalog results with scores
        catalog_payloads = []
        if catalog_results and isinstance(catalog_results, list):
            for result in catalog_results:
                if result and isinstance(result, dict):
                    payload = result.get("payload", {})
                    if payload:
                        # Inject score into payload
                        payload["score"] = result.get("score", 0)
                        catalog_payloads.append(payload)
        
        # Step 2: Extract knowledge_sources from catalog payloads
        knowledge_sources = [payload.get("knowledge_source") for payload in catalog_payloads if payload.get("knowledge_source")]
        
        # Step 3: Search knowledge base - TWO calls in PARALLEL
        source_based_knowledge = []
        direct_knowledge = []
        
        # Prepare tasks for parallel execution
        tasks = []
        
        # Task 1: Source-based search (only if knowledge_sources exist)
        if knowledge_sources:
            tasks.append(search_agent_knowledge_base(
                agent_id=agent_id,
                vector=embedding,
                knowledge_sources=knowledge_sources,
                limit=QDRANT_SOURCE_BASED_KNOWLEDGE_LIMIT
            ))
        else:
            tasks.append(None)
        
        # Task 2: Direct search (always executed)
        tasks.append(search_agent_knowledge_base(
            agent_id=agent_id,
            vector=embedding,
            limit=QDRANT_DIRECT_KNOWLEDGE_LIMIT
        ))
        
        # Execute both searches in parallel
        results = await asyncio.gather(*[task for task in tasks if task is not None])
        
        # Process results based on which tasks were executed
        if knowledge_sources:
            source_kb_results = results[0]
            direct_kb_results = results[1]
            
            if source_kb_results and isinstance(source_kb_results, list):
                for result in source_kb_results:
                    if result and isinstance(result, dict):
                        payload = result.get("payload", {})
                        if payload:
                            payload["score"] = result.get("score", 0)
                            source_based_knowledge.append(payload)
        else:
            direct_kb_results = results[0]
        
        if direct_kb_results and isinstance(direct_kb_results, list):
            for result in direct_kb_results:
                if result and isinstance(result, dict):
                    payload = result.get("payload", {})
                    if payload:
                        payload["score"] = result.get("score", 0)
                        direct_knowledge.append(payload)
        
        # Step 4: Merge and deduplicate knowledge base results
        all_knowledge = source_based_knowledge + direct_knowledge
        
        # Deduplicate based on knowledge_source and text_index, keep higher score
        seen = {}
        deduplicated = []
        for item in all_knowledge:
            key = (item.get("knowledge_source"), item.get("text_index"))
            if key not in seen:
                seen[key] = item
                deduplicated.append(item)
            else:
                if item.get("score", 0) > seen[key].get("score", 0):
                    deduplicated.remove(seen[key])
                    seen[key] = item
                    deduplicated.append(item)
        
        # Group by knowledge_source and combine text_content
        knowledge_groups = {}
        for item in deduplicated:
            knowledge_source = item.get("knowledge_source")
            if knowledge_source:
                if knowledge_source not in knowledge_groups:
                    knowledge_groups[knowledge_source] = {
                        "agent_id": item.get("agent_id"),
                        "knowledge_source": knowledge_source,
                        "knowledge_type": item.get("knowledge_type"),
                        "page_type": item.get("page_type"),
                        "created_at": item.get("created_at"),
                        "max_score": item.get("score", 0),
                        "text_contents": []
                    }
                else:
                    knowledge_groups[knowledge_source]["max_score"] = max(
                        knowledge_groups[knowledge_source]["max_score"],
                        item.get("score", 0)
                    )
                knowledge_groups[knowledge_source]["text_contents"].append({
                    "text_index": item.get("text_index"),
                    "text": item.get("text_content", "")
                })
        
        # Combine text_contents and create final merged list
        merged_knowledge = []
        for knowledge_source, group in knowledge_groups.items():
            sorted_texts = sorted(group["text_contents"], key=lambda x: x.get("text_index", 0))
            combined_text = "\n\n".join([
                f"[Chunk {t['text_index']}]\n{t['text']}" 
                for t in sorted_texts if t["text"]
            ])
            
            merged_knowledge.append({
                "agent_id": group["agent_id"],
                "knowledge_source": group["knowledge_source"],
                "knowledge_type": group["knowledge_type"],
                "page_type": group["page_type"],
                "created_at": group["created_at"],
                "score": group["max_score"],
                "text_content": combined_text
            })
        
        # Step 5: Final merge - combine catalog_results and merged_knowledge by knowledge_source
        final_merged = {}
        
        # First, add all catalog results
        for catalog_item in catalog_payloads:
            knowledge_source = catalog_item.get("knowledge_source")
            if knowledge_source:
                final_merged[knowledge_source] = {
                    "knowledge_source": knowledge_source,
                    "agent_id": catalog_item.get("agent_id"),
                    "page_type": catalog_item.get("page_type"),
                    "summary": catalog_item.get("summary"),
                    "product_name": catalog_item.get("product_name"),
                    "product_id": catalog_item.get("product_id"),
                    "category": catalog_item.get("category"),
                    "price": catalog_item.get("price"),
                    "currency": catalog_item.get("currency"),
                    "is_available": catalog_item.get("is_available"),
                    "knowledge_type": catalog_item.get("knowledge_type"),
                    "created_at": catalog_item.get("created_at"),
                    "score": catalog_item.get("score", 0),
                    "text_content": None
                }
        
        # Then, merge in the knowledge base text_content
        for kb_item in merged_knowledge:
            knowledge_source = kb_item.get("knowledge_source")
            if knowledge_source:
                if knowledge_source in final_merged:
                    final_merged[knowledge_source]["text_content"] = kb_item.get("text_content")
                    final_merged[knowledge_source]["score"] = max(
                        final_merged[knowledge_source]["score"],
                        kb_item.get("score", 0)
                    )
                else:
                    final_merged[knowledge_source] = {
                        "knowledge_source": knowledge_source,
                        "agent_id": kb_item.get("agent_id"),
                        "page_type": kb_item.get("page_type"),
                        "summary": None,
                        "product_name": None,
                        "product_id": None,
                        "category": None,
                        "price": None,
                        "currency": None,
                        "is_available": None,
                        "knowledge_type": kb_item.get("knowledge_type"),
                        "created_at": kb_item.get("created_at"),
                        "score": kb_item.get("score", 0),
                        "text_content": kb_item.get("text_content")
                    }
        
        # Convert to list and sort by score descending (highest relevance first)
        final_results = sorted(final_merged.values(), key=lambda x: x.get("score", 0), reverse=True)
        
        return final_results
        
    except Exception as e:
        logger.error(f"Error in search_and_merge_agent_knowledge for agent_id {agent_id}: {e}")
        return []