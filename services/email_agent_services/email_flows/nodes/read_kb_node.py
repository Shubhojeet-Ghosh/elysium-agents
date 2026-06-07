from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_LOG_STATUS_SKIPPED,
    NODE_TYPE_READ_KB,
)
from services.email_agent_services.email_knowledge.email_knowledge_constants import (
    RELEVANT_CHUNKS_LIMIT,
)
from services.email_agent_services.email_knowledge.email_knowledge_query_services import (
    retrieve_relevant_knowledge_chunks,
)

logger = get_logger()

NODE_ID = "read_kb"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_knowledge_id(agent: Dict[str, Any], config: Dict[str, Any]) -> str:
    config_id = (config.get("knowledge_id") or "").strip()
    if config_id:
        return config_id
    return (agent.get("knowledge_id") or "").strip()


def _normalize_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for chunk in chunks:
        normalized.append({
            "text_index": chunk.get("text_index", 0),
            "text_content": chunk.get("text_content", ""),
            "score": chunk.get("score", 0),
        })
    return normalized


async def execute_read_kb_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    RAG — embed compressed_query and retrieve top knowledge chunks from Qdrant.

    Writes context.kb_chunks, context.kb_title, context.kb_knowledge_id.
    """
    started_at = _utc_now()
    compressed_query = (context.get("compressed_query") or "").strip()
    knowledge_id = _resolve_knowledge_id(agent, config)
    limit = int(config.get("limit") or RELEVANT_CHUNKS_LIMIT)

    input_summary = {
        "knowledge_id": knowledge_id,
        "compressed_query_length": len(compressed_query),
        "limit": limit,
    }

    try:
        if not knowledge_id:
            context["kb_chunks"] = []
            context["kb_title"] = ""
            context["kb_knowledge_id"] = ""
            completed_at = _utc_now()
            node_log = {
                "node_id": NODE_ID,
                "node_type": NODE_TYPE_READ_KB,
                "status": NODE_LOG_STATUS_SKIPPED,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
                "input_summary": input_summary,
                "output": {
                    "context": context,
                    "skip_reason": "No knowledge_id on agent or node config.",
                    "chunk_count": 0,
                },
                "error": None,
            }
            return context, node_log

        if not compressed_query:
            raise ValueError(
                "compressed_query is empty — Load Thread Context must run first."
            )

        retrieval_result = await retrieve_relevant_knowledge_chunks(
            knowledge_id=knowledge_id,
            query=compressed_query,
            limit=limit,
        )

        if not retrieval_result.get("success"):
            raise ValueError(
                retrieval_result.get("message", "Failed to retrieve knowledge chunks.")
            )

        data = retrieval_result.get("data") or {}
        kb_chunks = _normalize_chunks(data.get("chunks") or [])
        kb_title = data.get("title", "") or ""

        context["kb_chunks"] = kb_chunks
        context["kb_title"] = kb_title
        context["kb_knowledge_id"] = knowledge_id

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_READ_KB,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "context": context,
                "knowledge_id": knowledge_id,
                "kb_title": kb_title,
                "chunk_count": len(kb_chunks),
                "chunks_preview": [
                    {
                        "text_index": chunk["text_index"],
                        "score": chunk["score"],
                        "text_content_preview": chunk["text_content"][:200],
                    }
                    for chunk in kb_chunks
                ],
                "downstream_hints": {
                    "generate_email": {
                        "uses": ["thread", "system_prompt", "kb_chunks"],
                    },
                    "read_tools": {
                        "uses": ["thread", "compressed_query", "kb_chunks"],
                    },
                },
            },
            "error": None,
        }
        return context, node_log

    except Exception as exc:
        logger.error(f"read_kb_node failed for knowledge_id={knowledge_id}: {exc}", exc_info=True)
        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        context.setdefault("errors", []).append({
            "node_id": NODE_ID,
            "message": str(exc),
        })

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_READ_KB,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
