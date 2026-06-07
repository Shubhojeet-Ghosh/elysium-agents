from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from logging_config import get_logger
from services.email_agent_services.email_knowledge.email_knowledge_constants import (
    EMAIL_KNOWLEDGE_MONGO_COLLECTION,
)
from services.mongo_services import get_collection

logger = get_logger()


def _format_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _format_knowledge_document(document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "knowledge_id": document.get("knowledge_id", ""),
        "team_id": document.get("team_id", ""),
        "title": document.get("title", ""),
        "status": document.get("status", ""),
        "chunk_count": document.get("chunk_count", 0),
        "char_count": document.get("char_count", 0),
        "created_at": _format_datetime(document.get("created_at")),
        "updated_at": _format_datetime(document.get("updated_at")),
    }


async def insert_knowledge_metadata(
    knowledge_id: str,
    team_id: str,
    title: str,
    chunk_count: int,
    char_count: int,
) -> Dict[str, Any]:
    """Insert a metadata document into the email-knowledge Mongo collection."""
    collection = get_collection(EMAIL_KNOWLEDGE_MONGO_COLLECTION)
    now = datetime.now(timezone.utc)

    document = {
        "knowledge_id": knowledge_id,
        "team_id": team_id,
        "title": title,
        "status": "indexed",
        "chunk_count": chunk_count,
        "char_count": char_count,
        "created_at": now,
        "updated_at": now,
    }

    await collection.insert_one(document)

    logger.info(f"Inserted knowledge metadata for knowledge_id={knowledge_id}, team_id={team_id}")

    return _format_knowledge_document(document)


async def get_knowledge_by_id(knowledge_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a knowledge metadata document by knowledge_id."""
    collection = get_collection(EMAIL_KNOWLEDGE_MONGO_COLLECTION)
    return await collection.find_one({"knowledge_id": knowledge_id.strip()})


async def list_team_knowledge_metadata(team_id: str) -> List[Dict[str, Any]]:
    """List all knowledge metadata documents for a team."""
    collection = get_collection(EMAIL_KNOWLEDGE_MONGO_COLLECTION)
    cursor = collection.find({"team_id": team_id.strip()}).sort("created_at", -1)

    documents: List[Dict[str, Any]] = []
    async for document in cursor:
        documents.append(_format_knowledge_document(document))

    return documents


async def delete_knowledge_metadata(knowledge_id: str) -> bool:
    """Delete a knowledge metadata document by knowledge_id. Returns True if deleted."""
    collection = get_collection(EMAIL_KNOWLEDGE_MONGO_COLLECTION)
    result = await collection.delete_one({"knowledge_id": knowledge_id.strip()})
    return result.deleted_count > 0
