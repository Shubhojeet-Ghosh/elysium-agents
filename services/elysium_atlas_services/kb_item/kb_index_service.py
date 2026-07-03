"""
Index a single knowledge item (kb_id) into Qdrant.

Callable from API BackgroundTasks or future agent-inline flows that create items then attach.
"""

from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from config.kb_item_constants import (
    COLLECTION_BY_SOURCE_TYPE,
    KB_CUSTOM_TEXTS_COLLECTION,
    KB_FILES_COLLECTION,
    KB_QA_PAIRS_COLLECTION,
    KB_STATUS_FAILED,
    KB_STATUS_READY,
    KB_URLS_COLLECTION,
    SOURCE_TYPE_CUSTOM_TEXT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_QA_PAIR,
    SOURCE_TYPE_URL,
)
from logging_config import get_logger
from services.elysium_atlas_services.kb_item.kb_qdrant_services import (
    delete_kb_item_from_qdrant,
    index_kb_chunks,
    upsert_kb_item_catalog,
)
from services.elysium_atlas_services.kb_item.kb_summary_services import resolve_kb_item_catalog_summary
from services.mongo_services import get_collection
from services.text_extraction_services import extract_texts_from_files
from services.web_services.url_services import fetch_multiple_urls_content, normalize_url

logger = get_logger()


async def _set_kb_status(collection_name: str, kb_id: str, status: str, extra: dict[str, Any] | None = None) -> None:
    from datetime import datetime, timezone

    update: dict[str, Any] = {"status": status, "updated_at": datetime.now(timezone.utc)}
    if extra:
        update.update(extra)
    await get_collection(collection_name).update_one({"_id": ObjectId(kb_id)}, {"$set": update})


async def _get_kb_document(kb_id: str, source_type: str) -> dict[str, Any] | None:
    try:
        collection_name = COLLECTION_BY_SOURCE_TYPE[source_type]
        return await get_collection(collection_name).find_one({"_id": ObjectId(kb_id)})
    except (InvalidId, KeyError):
        return None


async def index_kb_item(kb_id: str, source_type: str) -> bool:
    """
    Index one team knowledge item into team_knowledge_base + kb_item_catalog.

    Loads item from Mongo by kb_id and source_type; sets status ready/failed.
    """
    doc = await _get_kb_document(kb_id, source_type)
    if not doc:
        logger.error(f"index_kb_item: document not found kb_id={kb_id} source_type={source_type}")
        return False

    collection_name = COLLECTION_BY_SOURCE_TYPE[source_type]
    team_id = str(doc.get("team_id", ""))

    try:
        if source_type == SOURCE_TYPE_URL:
            await _index_url_item(kb_id, team_id, doc, collection_name)
        elif source_type == SOURCE_TYPE_FILE:
            await _index_file_item(kb_id, team_id, doc, collection_name)
        elif source_type == SOURCE_TYPE_CUSTOM_TEXT:
            await _index_custom_text_item(kb_id, team_id, doc, collection_name)
        elif source_type == SOURCE_TYPE_QA_PAIR:
            await _index_qa_pair_item(kb_id, team_id, doc, collection_name)
        else:
            raise ValueError(f"Unknown source_type: {source_type}")

        await _set_kb_status(collection_name, kb_id, KB_STATUS_READY)
        return True
    except Exception as e:
        logger.error(f"index_kb_item failed kb_id={kb_id}: {e}", exc_info=True)
        await _set_kb_status(collection_name, kb_id, KB_STATUS_FAILED, {"index_error": str(e)[:500]})
        return False


async def _index_url_item(kb_id: str, team_id: str, doc: dict, collection_name: str) -> None:
    url = doc.get("url") or ""
    normalized = normalize_url(url) if url else url
    results = await fetch_multiple_urls_content([normalized or url], batch_size=1)
    result = results[0] if results else {}
    if not result.get("success") or not result.get("text_content"):
        raise RuntimeError(result.get("error") or "Failed to fetch URL content")

    link = result.get("normalized_url") or result.get("url") or url
    text_content = result["text_content"]

    summary = await resolve_kb_item_catalog_summary(
        SOURCE_TYPE_URL, text_content, url=link
    )

    chunk_count = await index_kb_chunks(
        kb_id=kb_id,
        team_id=team_id,
        source_type=SOURCE_TYPE_URL,
        knowledge_source=link,
        text_content=text_content,
        knowledge_type="web_content",
    )
    await upsert_kb_item_catalog(
        kb_id=kb_id,
        team_id=team_id,
        source_type=SOURCE_TYPE_URL,
        knowledge_source=link,
        summary=summary,
        title=link,
        metadata={},
        chunk_count=chunk_count,
    )
    await _set_kb_status(
        collection_name,
        kb_id,
        doc.get("status") or KB_STATUS_READY,
        {"url": link, "summary": summary},
    )


async def _index_file_item(kb_id: str, team_id: str, doc: dict, collection_name: str) -> None:
    file_key = doc.get("file_key")
    file_name = doc.get("file_name")
    if not file_key or not file_name:
        raise RuntimeError("file_key and file_name are required before indexing")

    extracted = await extract_texts_from_files([{"file_name": file_name, "file_key": file_key}])
    if not extracted or not extracted[0].get("text"):
        raise RuntimeError("No text extracted from file")

    text_content = extracted[0]["text"]
    summary = await resolve_kb_item_catalog_summary(
        SOURCE_TYPE_FILE, text_content, file_name=file_name
    )

    chunk_count = await index_kb_chunks(
        kb_id=kb_id,
        team_id=team_id,
        source_type=SOURCE_TYPE_FILE,
        knowledge_source=file_key,
        text_content=text_content,
        knowledge_type="file_content",
    )
    await upsert_kb_item_catalog(
        kb_id=kb_id,
        team_id=team_id,
        source_type=SOURCE_TYPE_FILE,
        knowledge_source=file_key,
        summary=summary,
        title=file_name,
        metadata={},
        chunk_count=chunk_count,
    )
    await _set_kb_status(collection_name, kb_id, doc.get("status") or KB_STATUS_READY, {"summary": summary})


async def _index_custom_text_item(kb_id: str, team_id: str, doc: dict, collection_name: str) -> None:
    alias = doc.get("custom_text_alias")
    content = doc.get("content")
    if not alias or not content:
        raise RuntimeError("custom_text_alias and content are required")

    summary = await resolve_kb_item_catalog_summary(SOURCE_TYPE_CUSTOM_TEXT, content)
    chunk_count = await index_kb_chunks(
        kb_id=kb_id,
        team_id=team_id,
        source_type=SOURCE_TYPE_CUSTOM_TEXT,
        knowledge_source=alias,
        text_content=content,
        knowledge_type="custom_text",
    )
    await upsert_kb_item_catalog(
        kb_id=kb_id,
        team_id=team_id,
        source_type=SOURCE_TYPE_CUSTOM_TEXT,
        knowledge_source=alias,
        summary=summary,
        title=alias,
        metadata={},
        chunk_count=chunk_count,
    )
    await _set_kb_status(collection_name, kb_id, doc.get("status") or KB_STATUS_READY, {"summary": summary})


async def _index_qa_pair_item(kb_id: str, team_id: str, doc: dict, collection_name: str) -> None:
    alias = doc.get("qna_alias")
    question = doc.get("question")
    answer = doc.get("answer")
    if not alias or not question or not answer:
        raise RuntimeError("qna_alias, question, and answer are required")

    combined = f"Question: {question}\n\nAnswer: {answer}"
    summary = await resolve_kb_item_catalog_summary(
        SOURCE_TYPE_QA_PAIR,
        text_content="",
        question=question,
        answer=answer,
    )
    chunk_count = await index_kb_chunks(
        kb_id=kb_id,
        team_id=team_id,
        source_type=SOURCE_TYPE_QA_PAIR,
        knowledge_source=alias,
        text_content=combined,
        knowledge_type="qa_pair",
    )
    await upsert_kb_item_catalog(
        kb_id=kb_id,
        team_id=team_id,
        source_type=SOURCE_TYPE_QA_PAIR,
        knowledge_source=alias,
        summary=summary,
        title=question[:200],
        metadata={},
        chunk_count=chunk_count,
    )
    await _set_kb_status(collection_name, kb_id, doc.get("status") or KB_STATUS_READY, {"summary": summary})


async def delete_kb_item_index(kb_id: str) -> None:
    await delete_kb_item_from_qdrant(kb_id)
