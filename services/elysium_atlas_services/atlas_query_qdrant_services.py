from logging_config import get_logger
import asyncio
# import time  # profiling
from services.qdrant_api_services import search_qdrant_collection
from services.open_ai_services import get_embeddings
from services.elysium_atlas_services.qdrant_collection_helpers import (
    AGENT_WEB_CATALOG_COLLECTION_NAME,
    AGENT_KNOWLEDGE_BASE_COLLECTION_NAME
)
from config.retrieval_strategy_config import (
    DEFAULT_RETRIEVAL_STRATEGY,
    RETRIEVAL_STRATEGY_SIMPLE,
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


def _payloads_from_qdrant_results(search_results: list) -> list:
    """Extract payloads from Qdrant hits and attach relevance scores."""
    payloads = []
    if not search_results or not isinstance(search_results, list):
        return payloads

    for result in search_results:
        if result and isinstance(result, dict):
            payload = result.get("payload", {})
            if payload:
                payload["score"] = result.get("score", 0)
                payloads.append(payload)
    return payloads


def _deduplicate_knowledge_by_source_and_index(items: list) -> list:
    """Deduplicate chunks by (knowledge_source, text_index), keeping the highest score."""
    seen = {}
    deduplicated = []
    for item in items:
        key = (item.get("knowledge_source"), item.get("text_index"))
        if key not in seen:
            seen[key] = item
            deduplicated.append(item)
        elif item.get("score", 0) > seen[key].get("score", 0):
            deduplicated.remove(seen[key])
            seen[key] = item
            deduplicated.append(item)
    return deduplicated


def _group_knowledge_by_source(deduplicated: list) -> list:
    """Group chunks by knowledge_source and combine text_content (orchestrated-compatible shape)."""
    knowledge_groups = {}
    for item in deduplicated:
        knowledge_source = item.get("knowledge_source")
        if not knowledge_source:
            continue

        if knowledge_source not in knowledge_groups:
            knowledge_groups[knowledge_source] = {
                "agent_id": item.get("agent_id"),
                "knowledge_source": knowledge_source,
                "knowledge_type": item.get("knowledge_type"),
                "page_type": item.get("page_type"),
                "created_at": item.get("created_at"),
                "max_score": item.get("score", 0),
                "text_contents": [],
            }
        else:
            knowledge_groups[knowledge_source]["max_score"] = max(
                knowledge_groups[knowledge_source]["max_score"],
                item.get("score", 0),
            )

        knowledge_groups[knowledge_source]["text_contents"].append({
            "text_index": item.get("text_index"),
            "text": item.get("text_content", ""),
        })

    merged_knowledge = []
    for knowledge_source, group in knowledge_groups.items():
        sorted_texts = sorted(group["text_contents"], key=lambda x: x.get("text_index", 0))
        combined_text = "\n\n".join(
            f"[Chunk {t['text_index']}]\n{t['text']}"
            for t in sorted_texts
            if t["text"]
        )
        merged_knowledge.append({
            "agent_id": group["agent_id"],
            "knowledge_source": group["knowledge_source"],
            "knowledge_type": group["knowledge_type"],
            "page_type": group["page_type"],
            "created_at": group["created_at"],
            "score": group["max_score"],
            "text_content": combined_text,
        })

    return merged_knowledge


def _kb_merged_to_final_results(merged_knowledge: list) -> list:
    """Build final result list matching the orchestrated response schema (KB-only entries)."""
    final_results = []
    for kb_item in merged_knowledge:
        knowledge_source = kb_item.get("knowledge_source")
        if not knowledge_source:
            continue
        final_results.append({
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
            "text_content": kb_item.get("text_content"),
        })
    return sorted(final_results, key=lambda x: x.get("score", 0), reverse=True)


def _merge_catalog_with_knowledge(catalog_payloads: list, merged_knowledge: list) -> list:
    """Merge web catalog metadata with knowledge-base text (orchestrated path)."""
    final_merged = {}

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
                "text_content": None,
            }

    for kb_item in merged_knowledge:
        knowledge_source = kb_item.get("knowledge_source")
        if not knowledge_source:
            continue
        if knowledge_source in final_merged:
            final_merged[knowledge_source]["text_content"] = kb_item.get("text_content")
            final_merged[knowledge_source]["score"] = max(
                final_merged[knowledge_source]["score"],
                kb_item.get("score", 0),
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
                "text_content": kb_item.get("text_content"),
            }

    return sorted(final_merged.values(), key=lambda x: x.get("score", 0), reverse=True)


async def search_simple_agent_knowledge(agent_id: str, message: str) -> list:
    """
    Fast single-pass RAG: one embedding + one agent_knowledge_base search.
    Returns the same final result shape as the orchestrated path.
    """
    # rag_log = f"[rag simple agent_id={agent_id}]"
    try:
        # step_start = time.perf_counter()
        embeddings = await get_embeddings([message])
        embedding = embeddings[0]
        # logger.info(f"{rag_log} embeddings done in {(time.perf_counter() - step_start) * 1000:.0f}ms")

        # step_start = time.perf_counter()
        kb_results = await search_agent_knowledge_base(
            agent_id=agent_id,
            vector=embedding,
            limit=QDRANT_SOURCE_BASED_KNOWLEDGE_LIMIT,
        )
        # logger.info(f"{rag_log} qdrant_kb_search done in {(time.perf_counter() - step_start) * 1000:.0f}ms")

        # step_start = time.perf_counter()
        payloads = _payloads_from_qdrant_results(kb_results)
        deduplicated = _deduplicate_knowledge_by_source_and_index(payloads)
        merged_knowledge = _group_knowledge_by_source(deduplicated)
        final_results = _kb_merged_to_final_results(merged_knowledge)
        # logger.info(
        #     f"{rag_log} merge done in {(time.perf_counter() - step_start) * 1000:.0f}ms "
        #     f"(sources={len(final_results)}, chunks={len(payloads)})"
        # )
        return final_results

    except Exception as e:
        logger.error(f"Error in search_simple_agent_knowledge for agent_id {agent_id}: {e}")
        return []


async def search_orchestrated_agent_knowledge(agent_id: str, message: str) -> list:
    """
    Multi-step retrieval: web catalog discovery + dual knowledge-base searches + merge.
    """
    # rag_log = f"[rag orchestrated agent_id={agent_id}]"
    try:
        # step_start = time.perf_counter()
        embeddings = await get_embeddings([message])
        embedding = embeddings[0]
        # logger.info(f"{rag_log} embeddings done in {(time.perf_counter() - step_start) * 1000:.0f}ms")

        # step_start = time.perf_counter()
        catalog_results = await search_agent_web_catalog(
            agent_id, embedding, limit=QDRANT_WEB_CATALOG_LIMIT
        )
        catalog_payloads = _payloads_from_qdrant_results(catalog_results)
        # logger.info(
        #     f"{rag_log} qdrant_catalog_search done in {(time.perf_counter() - step_start) * 1000:.0f}ms "
        #     f"(catalog_hits={len(catalog_payloads)})"
        # )

        knowledge_sources = [
            payload.get("knowledge_source")
            for payload in catalog_payloads
            if payload.get("knowledge_source")
        ]

        # step_start = time.perf_counter()
        tasks = []

        if knowledge_sources:
            tasks.append(
                search_agent_knowledge_base(
                    agent_id=agent_id,
                    vector=embedding,
                    knowledge_sources=knowledge_sources,
                    limit=QDRANT_SOURCE_BASED_KNOWLEDGE_LIMIT,
                )
            )

        tasks.append(
            search_agent_knowledge_base(
                agent_id=agent_id,
                vector=embedding,
                limit=QDRANT_DIRECT_KNOWLEDGE_LIMIT,
            )
        )

        results = await asyncio.gather(*tasks)
        # logger.info(
        #     f"{rag_log} qdrant_kb_searches done in {(time.perf_counter() - step_start) * 1000:.0f}ms "
        #     f"(source_filtered={bool(knowledge_sources)})"
        # )

        source_based_knowledge = []
        if knowledge_sources:
            source_kb_results = results[0]
            direct_kb_results = results[1]
            source_based_knowledge = _payloads_from_qdrant_results(source_kb_results)
        else:
            direct_kb_results = results[0]

        direct_knowledge = _payloads_from_qdrant_results(direct_kb_results)

        # step_start = time.perf_counter()
        all_knowledge = source_based_knowledge + direct_knowledge
        deduplicated = _deduplicate_knowledge_by_source_and_index(all_knowledge)
        merged_knowledge = _group_knowledge_by_source(deduplicated)
        final_results = _merge_catalog_with_knowledge(catalog_payloads, merged_knowledge)
        # logger.info(
        #     f"{rag_log} merge done in {(time.perf_counter() - step_start) * 1000:.0f}ms "
        #     f"(sources={len(final_results)}, chunks={len(all_knowledge)})"
        # )
        return final_results

    except Exception as e:
        logger.error(f"Error in search_orchestrated_agent_knowledge for agent_id {agent_id}: {e}")
        return []


async def search_and_merge_agent_knowledge(
    agent_id: str,
    message: str,
    retrieval_strategy: str = DEFAULT_RETRIEVAL_STRATEGY,
):
    """
    Comprehensive search and merge function for agent knowledge.
    Searches both web catalog and knowledge base, merges results by knowledge_source,
    and returns sorted results by relevance score.
    
    Args:
        agent_id (str): The ID of the agent
        message (str): The user's message to search for
        retrieval_strategy (str): Retrieval mode — "simple" or "orchestrated" (default: "simple")
    
    Returns:
        list: Final merged and sorted results by knowledge_source
    """
    try:
        rag_log = f"[rag agent_id={agent_id}]"
        if retrieval_strategy == RETRIEVAL_STRATEGY_SIMPLE:
            logger.info(f"{rag_log} Running simple knowledge-base retrieval")
            final_results = await search_simple_agent_knowledge(agent_id, message)
        else:
            logger.info(f"{rag_log} Running orchestrated multi-step retrieval")
            final_results = await search_orchestrated_agent_knowledge(agent_id, message)

        # logger.info(
        #     f"[rag agent_id={agent_id}] retrieval_strategy={retrieval_strategy} "
        #     f"total={(time.perf_counter() - step_start) * 1000:.0f}ms"
        # )
        return final_results

    except Exception as e:
        logger.error(f"Error in search_and_merge_agent_knowledge for agent_id {agent_id}: {e}")
        return []