"""Qdrant read/write for team knowledge items (kb_id-scoped)."""

import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from config.kb_item_constants import KB_ITEM_CATALOG_COLLECTION, TEAM_KNOWLEDGE_BASE_COLLECTION
from logging_config import get_logger
from services.elysium_atlas_services.qdrant_collection_helpers import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    ensure_kb_qdrant_collections_exist,
)
from services.elysium_atlas_services.text_chunking_services import chunk_text_content
from services.open_ai_services import get_embeddings
from services.qdrant_services import get_qdrant_client_instance

logger = get_logger()


def _chunk_point_id(kb_id: str, text_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{kb_id}::chunk::{text_index}"))


def _catalog_point_id(kb_id: str) -> str:
    """Deterministic UUID for catalog (Qdrant rejects raw Mongo ObjectId hex as point id)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{kb_id}::catalog"))


async def delete_kb_item_from_qdrant(kb_id: str) -> None:
    await ensure_kb_qdrant_collections_exist()
    client = get_qdrant_client_instance()
    kb_filter = Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))])

    for collection in (TEAM_KNOWLEDGE_BASE_COLLECTION, KB_ITEM_CATALOG_COLLECTION):
        try:
            await client.delete(collection_name=collection, points_selector=kb_filter)
            logger.info(f"Deleted Qdrant points for kb_id={kb_id} from {collection}")
        except Exception as e:
            logger.error(f"Error deleting kb_id={kb_id} from {collection}: {e}", exc_info=True)


async def index_kb_chunks(
    *,
    kb_id: str,
    team_id: str,
    source_type: str,
    knowledge_source: str,
    text_content: str,
    knowledge_type: str,
) -> int:
    """Chunk text, embed, and upsert into team_knowledge_base. Returns chunk count."""
    await ensure_kb_qdrant_collections_exist()
    chunks = chunk_text_content(text_content)
    if not chunks:
        return 0

    embeddings = await get_embeddings(
        texts=chunks,
        model=EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIM,
    )

    now = datetime.now(timezone.utc).isoformat()
    points = [
        PointStruct(
            id=_chunk_point_id(kb_id, index),
            vector=embedding,
            payload={
                "kb_id": kb_id,
                "team_id": team_id,
                "source_type": source_type,
                "knowledge_source": knowledge_source,
                "text_index": index,
                "text_content": chunk_text,
                "knowledge_type": knowledge_type,
                "created_at": now,
            },
        )
        for index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings))
    ]

    client = get_qdrant_client_instance()
    await client.delete(
        collection_name=TEAM_KNOWLEDGE_BASE_COLLECTION,
        points_selector=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
    )
    await client.upsert(collection_name=TEAM_KNOWLEDGE_BASE_COLLECTION, points=points)
    logger.info(f"Indexed {len(points)} chunks for kb_id={kb_id}")
    return len(points)


async def upsert_kb_item_catalog(
    *,
    kb_id: str,
    team_id: str,
    source_type: str,
    knowledge_source: str,
    summary: str | None,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    chunk_count: int = 0,
) -> None:
    """Upsert one catalog point. Embeds summary when present; otherwise summary is null and vector is zero."""
    await ensure_kb_qdrant_collections_exist()
    if summary:
        embeddings = await get_embeddings(
            texts=[summary],
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIM,
        )
        vector = embeddings[0]
    else:
        vector = [0.0] * EMBEDDING_DIM
    now = datetime.now(timezone.utc).isoformat()

    point = PointStruct(
        id=_catalog_point_id(kb_id),
        vector=vector,
        payload={
            "kb_id": kb_id,
            "team_id": team_id,
            "source_type": source_type,
            "knowledge_source": knowledge_source,
            "title": title,
            "summary": summary,
            "metadata": metadata or {},
            "chunk_count": chunk_count,
            "created_at": now,
            "updated_at": now,
        },
    )

    client = get_qdrant_client_instance()
    await client.upsert(collection_name=KB_ITEM_CATALOG_COLLECTION, points=[point])
    logger.info(f"Upserted catalog point for kb_id={kb_id}")
