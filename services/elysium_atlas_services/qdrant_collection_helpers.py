from qdrant_client.models import Distance, VectorParams
from logging_config import get_logger
from services.qdrant_services import get_qdrant_client_instance
from config.kb_item_constants import (
    TEAM_KNOWLEDGE_BASE_COLLECTION,
    KB_ITEM_CATALOG_COLLECTION,
)

logger = get_logger()

EMBEDDING_DIM = 1536
EMBEDDING_MODEL = "text-embedding-3-small"

_team_kb_collection_ensured = False
_kb_catalog_collection_ensured = False


async def ensure_team_knowledge_base_collection_exists() -> None:
    global _team_kb_collection_ensured
    if _team_kb_collection_ensured:
        return

    try:
        client = get_qdrant_client_instance()
        collections = await client.get_collections()
        names = [col.name for col in collections.collections]

        if TEAM_KNOWLEDGE_BASE_COLLECTION not in names:
            await client.create_collection(
                collection_name=TEAM_KNOWLEDGE_BASE_COLLECTION,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {TEAM_KNOWLEDGE_BASE_COLLECTION}")

        for field_name in ("kb_id", "team_id", "source_type", "knowledge_source"):
            try:
                await client.create_payload_index(
                    collection_name=TEAM_KNOWLEDGE_BASE_COLLECTION,
                    field_name=field_name,
                    field_schema="keyword",
                )
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.debug(f"Payload index {field_name} on {TEAM_KNOWLEDGE_BASE_COLLECTION}: {e}")

        _team_kb_collection_ensured = True
    except Exception as e:
        logger.error(f"Error ensuring {TEAM_KNOWLEDGE_BASE_COLLECTION}: {e}")
        raise


async def ensure_kb_item_catalog_collection_exists() -> None:
    global _kb_catalog_collection_ensured
    if _kb_catalog_collection_ensured:
        return

    try:
        client = get_qdrant_client_instance()
        collections = await client.get_collections()
        names = [col.name for col in collections.collections]

        if KB_ITEM_CATALOG_COLLECTION not in names:
            await client.create_collection(
                collection_name=KB_ITEM_CATALOG_COLLECTION,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {KB_ITEM_CATALOG_COLLECTION}")

        for field_name in ("kb_id", "team_id", "source_type"):
            try:
                await client.create_payload_index(
                    collection_name=KB_ITEM_CATALOG_COLLECTION,
                    field_name=field_name,
                    field_schema="keyword",
                )
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.debug(f"Payload index {field_name} on {KB_ITEM_CATALOG_COLLECTION}: {e}")

        _kb_catalog_collection_ensured = True
    except Exception as e:
        logger.error(f"Error ensuring {KB_ITEM_CATALOG_COLLECTION}: {e}")
        raise


async def ensure_kb_qdrant_collections_exist() -> None:
    await ensure_team_knowledge_base_collection_exists()
    await ensure_kb_item_catalog_collection_exists()


# Backward-compatible alias for startup callers
ensure_agent_knowledge_base_collection_exists = ensure_team_knowledge_base_collection_exists

# Legacy names kept for any external imports; retrieval uses TEAM_KNOWLEDGE_BASE_COLLECTION directly
AGENT_KNOWLEDGE_BASE_COLLECTION_NAME = TEAM_KNOWLEDGE_BASE_COLLECTION
AGENT_WEB_CATALOG_COLLECTION_NAME = KB_ITEM_CATALOG_COLLECTION
