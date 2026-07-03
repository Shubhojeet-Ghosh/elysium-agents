from logging_config import get_logger
import time

from config.kb_item_constants import TEAM_KNOWLEDGE_BASE_COLLECTION
from config.retrieval_strategy_config import DEFAULT_RETRIEVAL_STRATEGY
from services.elysium_atlas_services.kb_item.kb_attachment_service import list_ready_kb_ids_for_agent
from services.open_ai_services import get_embeddings
from services.qdrant_api_services import search_qdrant_collection

logger = get_logger()

# Top chunk hits returned from team_knowledge_base per query
QDRANT_TEAM_KB_CHUNK_LIMIT = 15


async def search_team_knowledge_base(kb_ids: list[str], vector: list, limit: int = 15) -> list:
    """
    Search team_knowledge_base for chunks belonging to the given kb_ids.

    Args:
        kb_ids: Ready attached item IDs to scope the search
        vector: Query embedding
        limit: Maximum number of chunk results
    """
    if not kb_ids:
        return []

    try:
        filters = {
            "must": [
                {
                    "key": "kb_id",
                    "match": {"any": kb_ids},
                }
            ]
        }

        search_results = await search_qdrant_collection(
            collection_name=TEAM_KNOWLEDGE_BASE_COLLECTION,
            vector=vector,
            filters=filters,
            limit=limit,
            with_payload=True,
        )

        logger.info(
            f"Found {len(search_results)} chunk(s) in {TEAM_KNOWLEDGE_BASE_COLLECTION} "
            f"for {len(kb_ids)} kb_id(s)"
        )
        return search_results

    except Exception as e:
        logger.error(f"Error searching team knowledge base for kb_ids count={len(kb_ids)}: {e}")
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


def _deduplicate_knowledge_by_kb_id_and_index(items: list) -> list:
    """Deduplicate chunks by (kb_id, text_index), keeping the highest score."""
    seen = {}
    deduplicated = []
    for item in items:
        key = (item.get("kb_id"), item.get("text_index"))
        if key not in seen:
            seen[key] = item
            deduplicated.append(item)
        elif item.get("score", 0) > seen[key].get("score", 0):
            deduplicated.remove(seen[key])
            seen[key] = item
            deduplicated.append(item)
    return deduplicated


def _group_knowledge_by_kb_id(deduplicated: list) -> list:
    """Group chunks by kb_id and combine text_content for LLM consumption."""
    knowledge_groups = {}
    for item in deduplicated:
        kb_id = item.get("kb_id")
        if not kb_id:
            continue

        if kb_id not in knowledge_groups:
            knowledge_groups[kb_id] = {
                "kb_id": kb_id,
                "knowledge_source": item.get("knowledge_source"),
                "source_type": item.get("source_type"),
                "knowledge_type": item.get("knowledge_type"),
                "created_at": item.get("created_at"),
                "max_score": item.get("score", 0),
                "text_contents": [],
            }
        else:
            knowledge_groups[kb_id]["max_score"] = max(
                knowledge_groups[kb_id]["max_score"],
                item.get("score", 0),
            )

        knowledge_groups[kb_id]["text_contents"].append({
            "text_index": item.get("text_index"),
            "text": item.get("text_content", ""),
        })

    merged_knowledge = []
    for kb_id, group in knowledge_groups.items():
        sorted_texts = sorted(group["text_contents"], key=lambda x: x.get("text_index", 0))
        combined_text = "\n\n".join(
            f"[Chunk {t['text_index']}]\n{t['text']}"
            for t in sorted_texts
            if t["text"]
        )
        merged_knowledge.append({
            "kb_id": kb_id,
            "knowledge_source": group["knowledge_source"],
            "source_type": group["source_type"],
            "knowledge_type": group["knowledge_type"],
            "created_at": group["created_at"],
            "score": group["max_score"],
            "text_content": combined_text,
        })

    return merged_knowledge


def _kb_merged_to_final_results(merged_knowledge: list) -> list:
    """Build final result list for format_knowledge_base_string."""
    final_results = []
    for kb_item in merged_knowledge:
        kb_id = kb_item.get("kb_id")
        if not kb_id:
            continue
        final_results.append({
            "kb_id": kb_id,
            "knowledge_source": kb_item.get("knowledge_source"),
            "source_type": kb_item.get("source_type"),
            "knowledge_type": kb_item.get("knowledge_type"),
            "created_at": kb_item.get("created_at"),
            "score": kb_item.get("score", 0),
            "text_content": kb_item.get("text_content"),
            # Legacy catalog fields — unused in simple retrieval (phase 1)
            "page_type": None,
            "summary": None,
            "product_name": None,
            "product_id": None,
            "category": None,
            "price": None,
            "currency": None,
            "is_available": None,
        })
    return sorted(final_results, key=lambda x: x.get("score", 0), reverse=True)


async def search_simple_agent_knowledge(
    agent_id: str,
    message: str,
    *,
    ready_kb_ids: list[str] | None = None,
) -> list:
    """
    Single-pass RAG: resolve ready attachments → embed query → search team_knowledge_base.

    Pass ``ready_kb_ids`` when already resolved upstream (e.g. parallel load in chat handler).

    Returns merged results grouped by kb_id, sorted by relevance score.
    """
    rag_log = f"[rag agent_id={agent_id}]"
    step_start = time.perf_counter()
    try:
        if ready_kb_ids is None:
            kb_ids = await list_ready_kb_ids_for_agent(agent_id)
            logger.info(
                f"{rag_log} resolve_ready_kb_ids done in {(time.perf_counter() - step_start) * 1000:.0f}ms "
                f"(ready_kb_ids={len(kb_ids)})"
            )
        else:
            kb_ids = ready_kb_ids
            logger.info(
                f"{rag_log} resolve_ready_kb_ids skipped (pre-resolved, ready_kb_ids={len(kb_ids)})"
            )

        if not kb_ids:
            logger.info(f"No ready KB attachments for agent_id={agent_id}; skipping retrieval")
            return []

        step_start = time.perf_counter()
        embeddings = await get_embeddings([message])
        embedding = embeddings[0]
        logger.info(f"{rag_log} embeddings done in {(time.perf_counter() - step_start) * 1000:.0f}ms")

        step_start = time.perf_counter()
        kb_results = await search_team_knowledge_base(
            kb_ids=kb_ids,
            vector=embedding,
            limit=QDRANT_TEAM_KB_CHUNK_LIMIT,
        )
        logger.info(f"{rag_log} qdrant_search done in {(time.perf_counter() - step_start) * 1000:.0f}ms")

        step_start = time.perf_counter()
        payloads = _payloads_from_qdrant_results(kb_results)
        deduplicated = _deduplicate_knowledge_by_kb_id_and_index(payloads)
        merged_knowledge = _group_knowledge_by_kb_id(deduplicated)
        final_results = _kb_merged_to_final_results(merged_knowledge)
        logger.info(
            f"{rag_log} merge done in {(time.perf_counter() - step_start) * 1000:.0f}ms "
            f"(sources={len(final_results)}, chunks={len(payloads)})"
        )
        return final_results

    except Exception as e:
        logger.error(f"Error in search_simple_agent_knowledge for agent_id {agent_id}: {e}")
        return []


async def search_orchestrated_agent_knowledge(
    agent_id: str,
    message: str,
    *,
    ready_kb_ids: list[str] | None = None,
) -> list:
    """
    Orchestrated two-stage retrieval (catalog → chunks) — not implemented yet.

    Falls back to simple retrieval until kb_item_catalog routing ships.
    """
    return await search_simple_agent_knowledge(agent_id, message, ready_kb_ids=ready_kb_ids)


async def search_and_merge_agent_knowledge(
    agent_id: str,
    message: str,
    retrieval_strategy: str = DEFAULT_RETRIEVAL_STRATEGY,
    *,
    ready_kb_ids: list[str] | None = None,
):
    """
    Resolve attached ready KB items and return merged chunk context for the LLM.

    Both ``simple`` and ``orchestrated`` use simple single-pass retrieval for now.
    """
    try:
        rag_log = f"[rag agent_id={agent_id}]"
        logger.info(f"{rag_log} Running simple team KB retrieval (strategy={retrieval_strategy})")
        return await search_simple_agent_knowledge(agent_id, message, ready_kb_ids=ready_kb_ids)

    except Exception as e:
        logger.error(f"Error in search_and_merge_agent_knowledge for agent_id {agent_id}: {e}")
        return []
