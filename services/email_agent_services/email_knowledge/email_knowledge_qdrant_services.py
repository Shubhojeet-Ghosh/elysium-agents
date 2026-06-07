import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from logging_config import get_logger
from services.elysium_atlas_services.text_chunking_services import chunk_text_content
from services.email_agent_services.email_knowledge.email_knowledge_constants import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    EMAIL_KNOWLEDGE_QDRANT_COLLECTION,
)
from services.open_ai_services import get_embeddings
from services.qdrant_api_services import search_qdrant_collection
from services.qdrant_services import get_qdrant_client_instance

logger = get_logger()

_collection_ensured = False


async def ensure_email_knowledge_collection_exists() -> None:
    """Ensure the Qdrant email-knowledge collection and payload indexes exist."""
    global _collection_ensured

    if _collection_ensured:
        return

    try:
        client = get_qdrant_client_instance()
        collections = await client.get_collections()
        collection_names = [col.name for col in collections.collections]

        if EMAIL_KNOWLEDGE_QDRANT_COLLECTION not in collection_names:
            await client.create_collection(
                collection_name=EMAIL_KNOWLEDGE_QDRANT_COLLECTION,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            logger.info(
                f"Created Qdrant collection: {EMAIL_KNOWLEDGE_QDRANT_COLLECTION} "
                f"with dimension {EMBEDDING_DIM}"
            )

        for field_name in ("team_id", "knowledge_id"):
            try:
                await client.create_payload_index(
                    collection_name=EMAIL_KNOWLEDGE_QDRANT_COLLECTION,
                    field_name=field_name,
                    field_schema="keyword",
                )
            except Exception as e:
                error_msg = str(e).lower()
                if "already exists" not in error_msg and "index already" not in error_msg:
                    pass

        _collection_ensured = True

    except Exception as e:
        logger.error(f"Error ensuring email knowledge collection exists: {e}")
        raise


def _build_point_id(team_id: str, knowledge_id: str, text_index: int) -> str:
    composite_key = f"{team_id}:email_knowledge:{knowledge_id}:{text_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, composite_key))


async def index_knowledge_text_in_qdrant(
    team_id: str,
    knowledge_id: str,
    knowledge_text: str,
) -> Dict[str, Any]:
    """
    Chunk knowledge text, generate embeddings, and upsert points into Qdrant.

    Returns dict with total_chunks and errors.
    """
    try:
        await ensure_email_knowledge_collection_exists()

        chunks = chunk_text_content(knowledge_text)
        if not chunks:
            return {
                "success": False,
                "total_chunks": 0,
                "errors": ["No chunks generated from knowledge text."],
            }

        client = get_qdrant_client_instance()
        current_time = datetime.now(timezone.utc).isoformat()
        errors: List[str] = []

        embeddings = await get_embeddings(
            texts=chunks,
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIM,
        )

        points: List[PointStruct] = []
        for text_index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            points.append(
                PointStruct(
                    id=_build_point_id(team_id, knowledge_id, text_index),
                    vector=embedding,
                    payload={
                        "team_id": team_id,
                        "knowledge_id": knowledge_id,
                        "text_index": text_index,
                        "text_content": chunk_text,
                        "created_at": current_time,
                    },
                )
            )

        await client.upsert(
            collection_name=EMAIL_KNOWLEDGE_QDRANT_COLLECTION,
            points=points,
        )

        logger.info(
            f"Indexed {len(points)} chunks in Qdrant collection "
            f"'{EMAIL_KNOWLEDGE_QDRANT_COLLECTION}' for knowledge_id={knowledge_id}"
        )

        return {
            "success": True,
            "total_chunks": len(points),
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Error indexing knowledge in Qdrant: {e}", exc_info=True)
        return {
            "success": False,
            "total_chunks": 0,
            "errors": [str(e)],
        }


async def search_knowledge_chunks(
    knowledge_id: str,
    vector: List[float],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Search Qdrant for the most relevant chunks filtered by knowledge_id."""
    try:
        await ensure_email_knowledge_collection_exists()

        filters = {
            "must": [
                {
                    "key": "knowledge_id",
                    "match": {"value": knowledge_id},
                }
            ]
        }

        search_results = await search_qdrant_collection(
            collection_name=EMAIL_KNOWLEDGE_QDRANT_COLLECTION,
            vector=vector,
            filters=filters,
            limit=limit,
            with_payload=True,
        )

        chunks: List[Dict[str, Any]] = []
        for result in search_results:
            payload = result.get("payload") or {}
            chunks.append(
                {
                    "text_index": payload.get("text_index", 0),
                    "text_content": payload.get("text_content", ""),
                    "score": result.get("score", 0),
                }
            )

        logger.info(
            f"Found {len(chunks)} relevant chunks for knowledge_id={knowledge_id}"
        )
        return chunks

    except Exception as e:
        logger.error(
            f"Error searching knowledge chunks for knowledge_id={knowledge_id}: {e}",
            exc_info=True,
        )
        return []


async def delete_knowledge_from_qdrant(team_id: str, knowledge_id: str) -> Dict[str, Any]:
    """Delete all Qdrant points for a given team_id + knowledge_id."""
    try:
        await ensure_email_knowledge_collection_exists()
        client = get_qdrant_client_instance()

        delete_filter = Filter(
            must=[
                FieldCondition(key="team_id", match=MatchValue(value=team_id)),
                FieldCondition(key="knowledge_id", match=MatchValue(value=knowledge_id)),
            ]
        )

        await client.delete(
            collection_name=EMAIL_KNOWLEDGE_QDRANT_COLLECTION,
            points_selector=delete_filter,
        )

        logger.info(
            f"Deleted Qdrant points for team_id={team_id}, knowledge_id={knowledge_id}"
        )

        return {"success": True, "errors": []}

    except Exception as e:
        logger.error(f"Error deleting knowledge from Qdrant: {e}", exc_info=True)
        return {"success": False, "errors": [str(e)]}
