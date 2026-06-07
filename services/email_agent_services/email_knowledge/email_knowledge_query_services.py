from typing import Any, Dict, List

from logging_config import get_logger
from services.email_agent_services.email_knowledge.email_knowledge_constants import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    RELEVANT_CHUNKS_LIMIT,
)
from services.email_agent_services.email_knowledge.email_knowledge_mongo_services import (
    get_knowledge_by_id,
)
from services.email_agent_services.email_knowledge.email_knowledge_qdrant_services import (
    search_knowledge_chunks,
)
from services.open_ai_services import get_embeddings

logger = get_logger()


async def retrieve_relevant_knowledge_chunks(
    knowledge_id: str,
    query: str,
    limit: int = RELEVANT_CHUNKS_LIMIT,
) -> Dict[str, Any]:
    """
    Main retrieval service for email agent RAG.

    Embeds the user query, searches Qdrant filtered by knowledge_id,
    and returns the top relevant text chunks.
    """
    normalized_knowledge_id = knowledge_id.strip()
    normalized_query = query.strip()

    if not normalized_query:
        return {
            "success": False,
            "status_code": 400,
            "message": "query cannot be empty.",
        }

    knowledge_doc = await get_knowledge_by_id(normalized_knowledge_id)
    if not knowledge_doc:
        return {
            "success": False,
            "status_code": 404,
            "message": "Knowledge not found.",
        }

    try:
        query_embeddings = await get_embeddings(
            texts=[normalized_query],
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIM,
        )

        if not query_embeddings:
            return {
                "success": False,
                "status_code": 500,
                "message": "Failed to generate query embedding.",
            }

        chunks = await search_knowledge_chunks(
            knowledge_id=normalized_knowledge_id,
            vector=query_embeddings[0],
            limit=limit,
        )

        logger.info(
            f"Retrieved {len(chunks)} chunks for knowledge_id={normalized_knowledge_id}"
        )

        return {
            "success": True,
            "status_code": 200,
            "message": "Relevant chunks retrieved successfully.",
            "data": {
                "knowledge_id": normalized_knowledge_id,
                "team_id": knowledge_doc.get("team_id", ""),
                "title": knowledge_doc.get("title", ""),
                "query": normalized_query,
                "chunk_count": len(chunks),
                "chunks": chunks,
            },
        }

    except Exception as e:
        logger.error(
            f"Failed to retrieve chunks for knowledge_id={normalized_knowledge_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to retrieve relevant knowledge chunks.",
        }
