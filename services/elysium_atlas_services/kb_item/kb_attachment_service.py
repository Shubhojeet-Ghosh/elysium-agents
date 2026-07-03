"""
Agent ↔ KB item attachments.

One Mongo document per (agent_id, kb_id) pair in atlas_agent_kb_attachments.
Attach/detach does not re-index knowledge items.
"""

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from config.kb_item_constants import (
    AGENT_KB_ATTACHMENTS_COLLECTION,
    COLLECTION_BY_SOURCE_TYPE,
    DEFAULT_KB_LIST_PAGE_SIZE,
    KB_SOURCE_TYPES,
    KB_STATUS_READY,
    SOURCE_TYPE_CUSTOM_TEXT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_QA_PAIR,
    SOURCE_TYPE_URL,
)
from logging_config import get_logger
from services.elysium_atlas_services.agent_db_operations import get_agent_by_id
from services.mongo_services import get_collection

logger = get_logger()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_attachment(doc: dict[str, Any]) -> dict[str, Any]:
    out = {
        "attachment_id": str(doc["_id"]),
        "agent_id": doc.get("agent_id"),
        "kb_id": doc.get("kb_id"),
        "team_id": doc.get("team_id"),
        "source_type": doc.get("source_type"),
        "attached_by_user_id": doc.get("attached_by_user_id"),
    }
    attached_at = doc.get("attached_at")
    if isinstance(attached_at, datetime):
        out["attached_at"] = attached_at.isoformat()
    return out


async def _get_item_doc(kb_id: str, source_type: str) -> dict[str, Any] | None:
    try:
        collection_name = COLLECTION_BY_SOURCE_TYPE[source_type]
        return await get_collection(collection_name).find_one({"_id": ObjectId(kb_id)})
    except (InvalidId, KeyError):
        return None


def _item_display_fields(source_type: str, doc: dict[str, Any]) -> dict[str, Any]:
    if source_type == SOURCE_TYPE_URL:
        return {"title": doc.get("url"), "url": doc.get("url")}
    if source_type == SOURCE_TYPE_FILE:
        return {"title": doc.get("file_name"), "file_name": doc.get("file_name"), "file_key": doc.get("file_key")}
    if source_type == SOURCE_TYPE_CUSTOM_TEXT:
        return {
            "title": doc.get("custom_text_alias"),
            "custom_text_alias": doc.get("custom_text_alias"),
        }
    if source_type == SOURCE_TYPE_QA_PAIR:
        return {"title": doc.get("qna_alias"), "qna_alias": doc.get("qna_alias"), "question": doc.get("question")}
    return {"title": None}


async def _validate_attachment_item(
    kb_id: str,
    source_type: str,
    team_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if source_type not in KB_SOURCE_TYPES:
        return None, f"Invalid source_type: {source_type}."

    try:
        ObjectId(kb_id)
    except InvalidId:
        return None, f"Invalid kb_id: {kb_id}."

    doc = await _get_item_doc(kb_id, source_type)
    if not doc:
        return None, f"Knowledge item not found: {kb_id} ({source_type})."

    item_team_id = str(doc.get("team_id", ""))
    if item_team_id != team_id:
        return None, f"Knowledge item {kb_id} does not belong to this team."

    return doc, None


async def attach_kb_items_to_agent(
    agent_id: str,
    team_id: str,
    items: list[dict[str, str]],
    attached_by_user_id: str,
) -> tuple[bool, str | None]:
    """
    Attach kb_ids to an agent. Skips pairs that already exist.

    items: [{"kb_id": "...", "source_type": "url"|"file"|"custom_text"|"qa_pair"}, ...]
    """
    if not items:
        return True, None

    agent = await get_agent_by_id(agent_id)
    if not agent:
        return False, "Agent not found."

    agent_team_id = str(agent.get("team_id", ""))
    if agent_team_id != team_id:
        return False, "Agent does not belong to this team."

    collection = get_collection(AGENT_KB_ATTACHMENTS_COLLECTION)
    now = _now()

    for item in items:
        kb_id = str(item.get("kb_id", "")).strip()
        source_type = str(item.get("source_type", "")).strip()
        _, error = await _validate_attachment_item(kb_id, source_type, team_id)
        if error:
            return False, error

        await collection.update_one(
            {"agent_id": agent_id, "kb_id": kb_id},
            {
                "$setOnInsert": {
                    "agent_id": agent_id,
                    "kb_id": kb_id,
                    "team_id": team_id,
                    "source_type": source_type,
                    "attached_by_user_id": attached_by_user_id,
                    "attached_at": now,
                }
            },
            upsert=True,
        )

    logger.info(f"Attached {len(items)} KB item(s) to agent_id={agent_id}")
    return True, None


async def detach_kb_item_from_agent(agent_id: str, kb_id: str) -> tuple[bool, str | None]:
    """Detach one kb_id from an agent."""
    try:
        result = await get_collection(AGENT_KB_ATTACHMENTS_COLLECTION).delete_one(
            {"agent_id": agent_id, "kb_id": kb_id}
        )
    except InvalidId:
        return False, "Invalid kb_id."
    if result.deleted_count == 0:
        return False, "Attachment not found."
    return True, None


async def delete_attachments_for_agent(agent_id: str) -> int:
    """Remove all attachment rows for an agent. Returns deleted count."""
    result = await get_collection(AGENT_KB_ATTACHMENTS_COLLECTION).delete_many({"agent_id": agent_id})
    return result.deleted_count


async def delete_attachments_for_kb_id(kb_id: str) -> int:
    """Remove all attachment rows referencing a kb_id. Returns deleted count."""
    result = await get_collection(AGENT_KB_ATTACHMENTS_COLLECTION).delete_many({"kb_id": kb_id})
    return result.deleted_count


async def list_kb_attachments_for_agent(agent_id: str) -> list[dict[str, Any]]:
    """Return attachment rows for an agent with item metadata."""
    result = await list_agent_attached_kb_items(agent_id, source_type=None, page=1, limit=MAX_ATTACHED_LIST_PAGE_SIZE)
    return result["data"]


async def list_agent_attached_kb_items(
    agent_id: str,
    source_type: str | None,
    page: int = 1,
    limit: int = DEFAULT_KB_LIST_PAGE_SIZE,
) -> dict[str, Any]:
    """
    Paginated attached KB items for an agent, optionally filtered by source_type.

    Each row merges attachment metadata with the full team KB item document.
    """
    from services.elysium_atlas_services.kb_item.kb_item_services import (
        kb_pagination_meta,
        normalize_kb_pagination,
        serialize_kb_item_doc,
    )

    page, limit = normalize_kb_pagination(page, limit)
    attachment_collection = get_collection(AGENT_KB_ATTACHMENTS_COLLECTION)
    query: dict[str, Any] = {"agent_id": agent_id}
    if source_type is not None:
        query["source_type"] = source_type

    total = await attachment_collection.count_documents(query)
    meta = kb_pagination_meta(total, page, limit)
    page = meta["page"]

    if total == 0:
        return {"data": [], **meta}

    skip = (page - 1) * limit
    attachment_cursor = (
        attachment_collection.find(query)
        .sort([("attached_at", -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
    )

    attachment_rows: list[dict[str, Any]] = []
    kb_ids_by_type: dict[str, list[ObjectId]] = {}
    async for doc in attachment_cursor:
        row = _serialize_attachment(doc)
        attachment_rows.append(row)
        st = row.get("source_type")
        kb_id = row.get("kb_id")
        if not st or not kb_id:
            continue
        try:
            kb_ids_by_type.setdefault(st, []).append(ObjectId(kb_id))
        except InvalidId:
            continue

    item_docs: dict[str, dict[str, Any]] = {}
    for st, object_ids in kb_ids_by_type.items():
        collection_name = COLLECTION_BY_SOURCE_TYPE.get(st)
        if not collection_name or not object_ids:
            continue
        cursor = get_collection(collection_name).find({"_id": {"$in": object_ids}})
        async for item_doc in cursor:
            serialized = serialize_kb_item_doc(item_doc)
            item_docs[serialized["kb_id"]] = serialized

    data: list[dict[str, Any]] = []
    for attachment in attachment_rows:
        kb_id = attachment.get("kb_id")
        item = item_docs.get(kb_id) if kb_id else None
        if item:
            merged = {**item, **attachment}
        else:
            merged = {**attachment, "status": None}
        data.append(merged)

    return {"data": data, **meta}


MAX_ATTACHED_LIST_PAGE_SIZE = 500


async def list_kb_ids_for_agent(agent_id: str) -> list[dict[str, Any]]:
    """Return raw attachment pairs for an agent."""
    collection = get_collection(AGENT_KB_ATTACHMENTS_COLLECTION)
    cursor = collection.find({"agent_id": agent_id}, {"kb_id": 1, "source_type": 1, "_id": 0})
    return [{"kb_id": doc["kb_id"], "source_type": doc["source_type"]} async for doc in cursor]


async def list_ready_kb_ids_for_agent(agent_id: str) -> list[str]:
    """
    Return kb_ids attached to an agent whose Mongo item status is ``ready``.

    Used at retrieval time so indexing/failed/draft items are excluded from Qdrant search.
    """
    attachments = await list_kb_ids_for_agent(agent_id)
    if not attachments:
        return []

    kb_ids_by_type: dict[str, list[ObjectId]] = {}
    for attachment in attachments:
        source_type = attachment.get("source_type")
        kb_id = attachment.get("kb_id")
        if not source_type or not kb_id:
            continue
        try:
            kb_ids_by_type.setdefault(source_type, []).append(ObjectId(kb_id))
        except InvalidId:
            continue

    ready_kb_ids: list[str] = []
    for source_type, object_ids in kb_ids_by_type.items():
        collection_name = COLLECTION_BY_SOURCE_TYPE.get(source_type)
        if not collection_name or not object_ids:
            continue
        cursor = get_collection(collection_name).find(
            {"_id": {"$in": object_ids}, "status": KB_STATUS_READY},
            {"_id": 1},
        )
        async for doc in cursor:
            ready_kb_ids.append(str(doc["_id"]))

    return ready_kb_ids


def _dedupe_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        kb_id = str(item.get("kb_id", "")).strip()
        source_type = str(item.get("source_type", "")).strip()
        if not kb_id or not source_type or kb_id in seen:
            continue
        seen.add(kb_id)
        deduped.append({"kb_id": kb_id, "source_type": source_type})
    return deduped


async def sync_kb_attachments_for_agent(
    agent_id: str,
    team_id: str,
    desired_items: list[dict[str, str]],
    attached_by_user_id: str,
    *,
    replace: bool = True,
) -> tuple[bool, str | None]:
    """
    Sync agent attachments to the desired set.

    replace=True: detach items not in desired_items, attach missing ones.
    replace=False: only attach items not already linked (never detach).
    """
    desired_items = _dedupe_items(desired_items)
    collection = get_collection(AGENT_KB_ATTACHMENTS_COLLECTION)

    if replace:
        desired_kb_ids = {item["kb_id"] for item in desired_items}
        current_cursor = collection.find({"agent_id": agent_id}, {"kb_id": 1})
        async for doc in current_cursor:
            current_kb_id = doc.get("kb_id")
            if current_kb_id and current_kb_id not in desired_kb_ids:
                await collection.delete_one({"agent_id": agent_id, "kb_id": current_kb_id})

    if not desired_items:
        if replace:
            logger.info(f"Cleared all KB attachments for agent_id={agent_id}")
        return True, None

    if replace:
        to_attach = desired_items
    else:
        existing = {row["kb_id"] for row in await list_kb_ids_for_agent(agent_id)}
        to_attach = [item for item in desired_items if item["kb_id"] not in existing]

    return await attach_kb_items_to_agent(agent_id, team_id, to_attach, attached_by_user_id)
