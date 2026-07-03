"""
Team knowledge item CRUD — reusable from KB library APIs and future agent-inline create+attach.

Phase 2 will call these functions then attach via kb_attachment_service.
"""

import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from config.elysium_atlas_s3_config import ELYSIUM_ATLAS_BUCKET_NAME
from config.kb_item_constants import (
    COLLECTION_BY_SOURCE_TYPE,
    DEFAULT_KB_LIST_PAGE_SIZE,
    KB_CUSTOM_TEXTS_COLLECTION,
    KB_FILES_COLLECTION,
    KB_QA_PAIRS_COLLECTION,
    KB_STATUS_DRAFT,
    KB_STATUS_INDEXING,
    KB_URLS_COLLECTION,
    MAX_KB_LIST_PAGE_SIZE,
    SOURCE_TYPE_CUSTOM_TEXT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_QA_PAIR,
    SOURCE_TYPE_URL,
)
from logging_config import get_logger
from services.aws_services.s3_service import generate_presigned_upload_url
from services.elysium_atlas_services.kb_item.kb_index_service import delete_kb_item_index, index_kb_item
from services.mongo_services import get_collection
from services.web_services.url_services import normalize_url

logger = get_logger()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_pagination(page: int, limit: int) -> tuple[int, int]:
    return max(1, page), max(1, min(limit, MAX_KB_LIST_PAGE_SIZE))


def _pagination_meta(total: int, page: int, limit: int) -> dict[str, Any]:
    if total == 0:
        return {
            "total": 0,
            "page": 1,
            "limit": limit,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
        }
    total_pages = (total + limit - 1) // limit
    page = min(page, total_pages)
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


def _serialize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    out["kb_id"] = str(out.pop("_id"))
    for key in ("created_at", "updated_at"):
        val = out.get(key)
        if isinstance(val, datetime):
            out[key] = val.isoformat()
    return out


def serialize_kb_item_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Public serializer for KB item Mongo documents."""
    return _serialize_doc(doc)


def normalize_kb_pagination(page: int, limit: int) -> tuple[int, int]:
    return _normalize_pagination(page, limit)


def kb_pagination_meta(total: int, page: int, limit: int) -> dict[str, Any]:
    return _pagination_meta(total, page, limit)


async def _list_team_collection(
    collection_name: str,
    team_id: str,
    page: int = 1,
    limit: int = DEFAULT_KB_LIST_PAGE_SIZE,
) -> dict[str, Any]:
    page, limit = _normalize_pagination(page, limit)
    collection = get_collection(collection_name)
    query = {"team_id": team_id}
    total = await collection.count_documents(query)
    meta = _pagination_meta(total, page, limit)
    page = meta["page"]
    if total == 0:
        return {"data": [], **meta}
    skip = (page - 1) * limit
    cursor = (
        collection.find(query)
        .sort([("updated_at", -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
    )
    data = [_serialize_doc(doc) async for doc in cursor]
    return {"data": data, **meta}


_SEARCH_FIELDS_BY_SOURCE_TYPE: dict[str, list[str]] = {
    SOURCE_TYPE_URL: ["url", "summary"],
    SOURCE_TYPE_FILE: ["file_name", "file_key"],
    SOURCE_TYPE_CUSTOM_TEXT: ["custom_text_alias", "content"],
    SOURCE_TYPE_QA_PAIR: ["qna_alias", "question", "answer"],
}

_LIST_RESPONSE_KEY_BY_SOURCE_TYPE: dict[str, str] = {
    SOURCE_TYPE_URL: "urls",
    SOURCE_TYPE_FILE: "files",
    SOURCE_TYPE_CUSTOM_TEXT: "custom_texts",
    SOURCE_TYPE_QA_PAIR: "qa_pairs",
}


def list_response_key_for_source_type(source_type: str) -> str:
    return _LIST_RESPONSE_KEY_BY_SOURCE_TYPE[source_type]


def _case_insensitive_substring_filter(search_query: str) -> dict[str, Any]:
    escaped = re.escape(search_query.strip())
    return {"$regex": escaped, "$options": "i"}


async def _search_team_collection(
    collection_name: str,
    team_id: str,
    search_fields: list[str],
    search_query: str,
    page: int = 1,
    limit: int = DEFAULT_KB_LIST_PAGE_SIZE,
) -> dict[str, Any]:
    page, limit = _normalize_pagination(page, limit)
    collection = get_collection(collection_name)
    pattern = _case_insensitive_substring_filter(search_query)
    query: dict[str, Any] = {
        "team_id": team_id,
        "$or": [{field: pattern} for field in search_fields],
    }
    total = await collection.count_documents(query)
    meta = _pagination_meta(total, page, limit)
    page = meta["page"]
    if total == 0:
        return {"data": [], **meta}
    skip = (page - 1) * limit
    cursor = (
        collection.find(query)
        .sort([("updated_at", -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
    )
    data = [_serialize_doc(doc) async for doc in cursor]
    return {"data": data, **meta}


async def search_kb_items_for_team(
    team_id: str,
    source_type: str,
    search_query: str,
    page: int = 1,
    limit: int = DEFAULT_KB_LIST_PAGE_SIZE,
) -> dict[str, Any]:
    """Case-insensitive substring search within one KB type for the team."""
    collection_name = COLLECTION_BY_SOURCE_TYPE[source_type]
    search_fields = _SEARCH_FIELDS_BY_SOURCE_TYPE[source_type]
    return await _search_team_collection(
        collection_name,
        team_id,
        search_fields,
        search_query,
        page,
        limit,
    )


async def get_kb_item_team_id(kb_id: str, source_type: str) -> str | None:
    doc = await _get_doc(kb_id, source_type)
    if not doc:
        return None
    team_id = doc.get("team_id")
    return str(team_id) if team_id else None


async def find_url_kb_id_for_team(team_id: str, raw_url: str) -> str | None:
    """Return kb_id if this normalized URL already exists for the team."""
    url = normalize_url(raw_url.strip()) if raw_url else ""
    if not url:
        return None
    doc = await get_collection(KB_URLS_COLLECTION).find_one({"team_id": team_id, "url": url})
    return str(doc["_id"]) if doc else None


async def find_file_kb_id_for_team(team_id: str, file_name: str) -> str | None:
    """Return kb_id if a finalized file with this name already exists for the team."""
    name = file_name.strip()
    if not name:
        return None
    doc = await get_collection(KB_FILES_COLLECTION).find_one(
        {
            "team_id": team_id,
            "file_name": name,
            "file_key": {"$exists": True, "$ne": ""},
        },
        sort=[("updated_at", -1), ("_id", -1)],
    )
    return str(doc["_id"]) if doc else None


async def find_custom_text_kb_id_for_team(team_id: str, custom_text_alias: str) -> str | None:
    alias = custom_text_alias.strip()
    if not alias:
        return None
    doc = await get_collection(KB_CUSTOM_TEXTS_COLLECTION).find_one(
        {"team_id": team_id, "custom_text_alias": alias},
    )
    return str(doc["_id"]) if doc else None


async def find_qa_pair_kb_id_for_team(team_id: str, qna_alias: str) -> str | None:
    alias = qna_alias.strip()
    if not alias:
        return None
    doc = await get_collection(KB_QA_PAIRS_COLLECTION).find_one(
        {"team_id": team_id, "qna_alias": alias},
    )
    return str(doc["_id"]) if doc else None


async def delete_draft_file_item(team_id: str, kb_id: str) -> None:
    """Remove an unused draft file shell (no finalize). Ignores missing or non-draft rows."""
    doc = await _get_doc(kb_id, SOURCE_TYPE_FILE)
    if not doc or doc.get("team_id") != team_id:
        return
    if doc.get("status") != KB_STATUS_DRAFT or doc.get("file_key"):
        return
    await get_collection(KB_FILES_COLLECTION).delete_one(
        {"_id": ObjectId(kb_id), "team_id": team_id, "status": KB_STATUS_DRAFT},
    )


async def _get_doc(kb_id: str, source_type: str) -> dict[str, Any] | None:
    try:
        name = COLLECTION_BY_SOURCE_TYPE[source_type]
        return await get_collection(name).find_one({"_id": ObjectId(kb_id)})
    except (InvalidId, KeyError):
        return None


def kb_item_s3_folder(team_id: str, kb_id: str) -> str:
    return f"teams/{team_id}/kb_items/{kb_id}/files"


# --- URLs (batch create — reusable) ---


async def create_url_items_for_team(
    team_id: str,
    user_id: str,
    urls: list[str],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Create one Mongo doc + kb_id per URL. Caller schedules index_kb_item per id.

    Returns (items, error_message).
    """
    collection = get_collection(KB_URLS_COLLECTION)
    now = _now()
    created: list[dict[str, Any]] = []

    for raw_url in urls:
        url = normalize_url(raw_url.strip()) if raw_url else ""
        if not url:
            continue
        doc = {
            "team_id": team_id,
            "created_by_user_id": user_id,
            "url": url,
            "status": KB_STATUS_INDEXING,
            "created_at": now,
            "updated_at": now,
        }
        result = await collection.insert_one(doc)
        kb_id = str(result.inserted_id)
        created.append({"kb_id": kb_id, "url": url, "status": KB_STATUS_INDEXING})

    if not created:
        return None, "No valid URLs provided."

    return created, None


async def list_urls_for_team(team_id: str, page: int = 1, limit: int = DEFAULT_KB_LIST_PAGE_SIZE) -> dict[str, Any]:
    return await _list_team_collection(KB_URLS_COLLECTION, team_id, page, limit)


async def get_url_item(kb_id: str) -> dict[str, Any] | None:
    doc = await _get_doc(kb_id, SOURCE_TYPE_URL)
    return _serialize_doc(doc) if doc else None


async def update_url_item(kb_id: str, team_id: str, url: str) -> tuple[dict[str, Any] | None, str | None]:
    normalized = normalize_url(url.strip())
    collection = get_collection(KB_URLS_COLLECTION)
    result = await collection.update_one(
        {"_id": ObjectId(kb_id), "team_id": team_id},
        {"$set": {"url": normalized, "status": KB_STATUS_INDEXING, "updated_at": _now()}},
    )
    if result.matched_count == 0:
        return None, "URL item not found."
    return {"kb_id": kb_id, "url": normalized, "status": KB_STATUS_INDEXING}, None


async def delete_url_item(kb_id: str, team_id: str) -> bool:
    return await _delete_item(kb_id, team_id, SOURCE_TYPE_URL)


# --- Files ---


async def create_file_item_for_team(
    team_id: str,
    user_id: str,
    file_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    collection = get_collection(KB_FILES_COLLECTION)
    now = _now()
    doc = {
        "team_id": team_id,
        "created_by_user_id": user_id,
        "file_name": file_name,
        "status": KB_STATUS_DRAFT,
        "created_at": now,
        "updated_at": now,
    }
    result = await collection.insert_one(doc)
    kb_id = str(result.inserted_id)
    return {"kb_id": kb_id, "file_name": file_name, "status": KB_STATUS_DRAFT}, None


async def generate_file_presigned_urls(
    team_id: str,
    kb_id: str,
    files: list[dict[str, str]],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    doc = await _get_doc(kb_id, SOURCE_TYPE_FILE)
    if not doc or doc.get("team_id") != team_id:
        return None, "File item not found."

    folder = kb_item_s3_folder(team_id, kb_id)
    presigned: list[dict[str, Any]] = []
    for f in files:
        file_name = f.get("file_name", "").strip()
        filetype = f.get("filetype") or "application/octet-stream"
        if not file_name:
            continue
        entry = generate_presigned_upload_url(
            ELYSIUM_ATLAS_BUCKET_NAME,
            folder,
            file_name,
            filetype,
            visibility="private",
        )
        if entry:
            presigned.append(entry)
    if not presigned:
        return None, "Failed to generate presigned URLs."
    return presigned, None


async def finalize_file_item(
    team_id: str,
    kb_id: str,
    file_key: str,
) -> tuple[dict[str, Any] | None, str | None]:
    doc = await _get_doc(kb_id, SOURCE_TYPE_FILE)
    if not doc or doc.get("team_id") != team_id:
        return None, "File item not found."
    if not file_key.startswith(f"teams/{team_id}/kb_items/{kb_id}/"):
        return None, "file_key does not match this kb item."

    file_name = doc.get("file_name") or file_key.rsplit("/", 1)[-1]
    await get_collection(KB_FILES_COLLECTION).update_one(
        {"_id": ObjectId(kb_id)},
        {
            "$set": {
                "file_key": file_key,
                "file_name": file_name,
                "status": KB_STATUS_INDEXING,
                "updated_at": _now(),
            }
        },
    )
    return {"kb_id": kb_id, "file_key": file_key, "status": KB_STATUS_INDEXING}, None


async def list_files_for_team(team_id: str, page: int = 1, limit: int = DEFAULT_KB_LIST_PAGE_SIZE) -> dict[str, Any]:
    return await _list_team_collection(KB_FILES_COLLECTION, team_id, page, limit)


async def get_file_item(kb_id: str) -> dict[str, Any] | None:
    doc = await _get_doc(kb_id, SOURCE_TYPE_FILE)
    return _serialize_doc(doc) if doc else None


async def delete_file_item(kb_id: str, team_id: str) -> bool:
    return await _delete_item(kb_id, team_id, SOURCE_TYPE_FILE)


# --- Custom texts ---


async def create_custom_text_for_team(
    team_id: str,
    user_id: str,
    custom_text_alias: str,
    content: str,
) -> tuple[dict[str, Any] | None, str | None]:
    collection = get_collection(KB_CUSTOM_TEXTS_COLLECTION)
    now = _now()
    doc = {
        "team_id": team_id,
        "created_by_user_id": user_id,
        "custom_text_alias": custom_text_alias,
        "content": content,
        "status": KB_STATUS_INDEXING,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await collection.insert_one(doc)
    except DuplicateKeyError:
        return None, f"custom_text_alias '{custom_text_alias}' already exists for this team."
    kb_id = str(result.inserted_id)
    return {
        "kb_id": kb_id,
        "custom_text_alias": custom_text_alias,
        "status": KB_STATUS_INDEXING,
    }, None


async def update_custom_text_item(
    kb_id: str,
    team_id: str,
    custom_text_alias: str | None,
    content: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    updates: dict[str, Any] = {"updated_at": _now(), "status": KB_STATUS_INDEXING}
    if custom_text_alias is not None:
        updates["custom_text_alias"] = custom_text_alias
    if content is not None:
        updates["content"] = content
    if len(updates) <= 2:
        return None, "No fields to update."

    collection = get_collection(KB_CUSTOM_TEXTS_COLLECTION)
    try:
        result = await collection.update_one(
            {"_id": ObjectId(kb_id), "team_id": team_id},
            {"$set": updates},
        )
    except DuplicateKeyError:
        return None, "custom_text_alias already exists for this team."
    if result.matched_count == 0:
        return None, "Custom text item not found."
    return {"kb_id": kb_id, "status": KB_STATUS_INDEXING}, None


async def list_custom_texts_for_team(
    team_id: str, page: int = 1, limit: int = DEFAULT_KB_LIST_PAGE_SIZE
) -> dict[str, Any]:
    return await _list_team_collection(KB_CUSTOM_TEXTS_COLLECTION, team_id, page, limit)


async def get_custom_text_item(kb_id: str) -> dict[str, Any] | None:
    doc = await _get_doc(kb_id, SOURCE_TYPE_CUSTOM_TEXT)
    return _serialize_doc(doc) if doc else None


async def delete_custom_text_item(kb_id: str, team_id: str) -> bool:
    return await _delete_item(kb_id, team_id, SOURCE_TYPE_CUSTOM_TEXT)


# --- Q&A ---


async def create_qa_pair_for_team(
    team_id: str,
    user_id: str,
    qna_alias: str,
    question: str,
    answer: str,
) -> tuple[dict[str, Any] | None, str | None]:
    collection = get_collection(KB_QA_PAIRS_COLLECTION)
    now = _now()
    doc = {
        "team_id": team_id,
        "created_by_user_id": user_id,
        "qna_alias": qna_alias,
        "question": question,
        "answer": answer,
        "status": KB_STATUS_INDEXING,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await collection.insert_one(doc)
    except DuplicateKeyError:
        return None, f"qna_alias '{qna_alias}' already exists for this team."
    kb_id = str(result.inserted_id)
    return {"kb_id": kb_id, "qna_alias": qna_alias, "status": KB_STATUS_INDEXING}, None


async def update_qa_pair_item(
    kb_id: str,
    team_id: str,
    qna_alias: str | None,
    question: str | None,
    answer: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    updates: dict[str, Any] = {"updated_at": _now(), "status": KB_STATUS_INDEXING}
    if qna_alias is not None:
        updates["qna_alias"] = qna_alias
    if question is not None:
        updates["question"] = question
    if answer is not None:
        updates["answer"] = answer
    if len(updates) <= 2:
        return None, "No fields to update."

    collection = get_collection(KB_QA_PAIRS_COLLECTION)
    try:
        result = await collection.update_one(
            {"_id": ObjectId(kb_id), "team_id": team_id},
            {"$set": updates},
        )
    except DuplicateKeyError:
        return None, "qna_alias already exists for this team."
    if result.matched_count == 0:
        return None, "Q&A item not found."
    return {"kb_id": kb_id, "status": KB_STATUS_INDEXING}, None


async def list_qa_pairs_for_team(
    team_id: str, page: int = 1, limit: int = DEFAULT_KB_LIST_PAGE_SIZE
) -> dict[str, Any]:
    return await _list_team_collection(KB_QA_PAIRS_COLLECTION, team_id, page, limit)


async def get_qa_pair_item(kb_id: str) -> dict[str, Any] | None:
    doc = await _get_doc(kb_id, SOURCE_TYPE_QA_PAIR)
    return _serialize_doc(doc) if doc else None


async def delete_qa_pair_item(kb_id: str, team_id: str) -> bool:
    return await _delete_item(kb_id, team_id, SOURCE_TYPE_QA_PAIR)


# --- Shared delete / reindex ---


async def _delete_item(kb_id: str, team_id: str, source_type: str) -> bool:
    try:
        from services.elysium_atlas_services.kb_item.kb_attachment_service import delete_attachments_for_kb_id

        name = COLLECTION_BY_SOURCE_TYPE[source_type]
        result = await get_collection(name).delete_one({"_id": ObjectId(kb_id), "team_id": team_id})
        if result.deleted_count == 0:
            return False
        await delete_attachments_for_kb_id(kb_id)
        await delete_kb_item_index(kb_id)
        return True
    except InvalidId:
        return False


async def reindex_kb_item(kb_id: str, team_id: str, source_type: str) -> tuple[bool, str | None]:
    doc = await _get_doc(kb_id, source_type)
    if not doc or doc.get("team_id") != team_id:
        return False, "Item not found."
    name = COLLECTION_BY_SOURCE_TYPE[source_type]
    await get_collection(name).update_one(
        {"_id": ObjectId(kb_id)},
        {"$set": {"status": KB_STATUS_INDEXING, "updated_at": _now()}},
    )
    return True, None
