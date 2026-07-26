"""
Append-only audit trail for atlas chat session lifecycle events.

Collection: atlas_chat_session_audits
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from logging_config import get_logger
from services.mongo_services import get_collection
from services.elysium_atlas_services.atlas_chat_session_services import format_utc_datetime_for_client

logger = get_logger()

AUDIT_COLLECTION = "atlas_chat_session_audits"

AUDIT_EVENT_VISITOR_FIRST_CONNECTED = "visitor_first_connected"
AUDIT_EVENT_VISITOR_FIRST_MESSAGE = "visitor_first_message"
AUDIT_EVENT_TAKEOVER_STARTED = "takeover_started"
AUDIT_EVENT_TAKEOVER_RELEASED = "takeover_released"
AUDIT_EVENT_SESSION_RESOLVED = "session_resolved"
AUDIT_EVENT_SESSION_REACTIVATED = "session_reactivated"
AUDIT_EVENT_HANDOVER_REQUESTED = "handover_requested"
AUDIT_EVENT_HANDOVER_CONTACT_SUBMITTED = "handover_contact_submitted"
AUDIT_EVENT_HANDOVER_CONTACT_DECLINED = "handover_contact_declined"
AUDIT_EVENT_HANDOVER_ASSIGNED = "handover_assigned"

AUDIT_ACTOR_VISITOR = "visitor"
AUDIT_ACTOR_TEAM_MEMBER = "team_member"
AUDIT_ACTOR_SYSTEM = "system"


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def record_chat_session_audit(
    agent_id: str,
    chat_session_id: str,
    event_type: str,
    *,
    actor_user_id: str | None = None,
    actor_type: str = AUDIT_ACTOR_SYSTEM,
    metadata: dict[str, Any] | None = None,
    occurred_at: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """
    Insert one lifecycle audit document. Returns the serialized audit row or None on failure.
    """
    try:
        if not agent_id or not chat_session_id or not event_type:
            return None

        timestamp = occurred_at or _utc_now()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)

        document: dict[str, Any] = {
            "audit_id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "event_type": event_type,
            "actor_type": actor_type,
            "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
            "metadata": metadata or {},
            "created_at": timestamp,
        }

        collection = get_collection(AUDIT_COLLECTION)
        result = await collection.insert_one(document)
        document["_id"] = str(result.inserted_id)

        logger.info(
            "Chat session audit recorded: event=%s chat_session_id=%s agent_id=%s actor=%s",
            event_type,
            chat_session_id,
            agent_id,
            actor_user_id,
        )
        return serialize_chat_session_audit(document)

    except Exception as e:
        logger.error(
            f"Failed to record chat session audit {event_type} for {chat_session_id}: {e}",
            exc_info=True,
        )
        return None


def serialize_chat_session_audit(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize an audit document for API/socket responses."""
    if not document:
        return None

    serialized = dict(document)
    mongo_id = serialized.pop("_id", None)
    if mongo_id is not None:
        serialized["_id"] = str(mongo_id)

    created_at = serialized.get("created_at")
    if isinstance(created_at, datetime.datetime):
        serialized["created_at"] = format_utc_datetime_for_client(created_at)

    return serialized


def _clamp_audit_query_limit(limit: int | None) -> int:
    if limit is None or limit < 1:
        return 50
    return min(limit, 500)


def _build_chat_session_audit_query(
    agent_id: str,
    *,
    chat_session_id: str | None = None,
    event_type: str | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {"agent_id": agent_id}
    if chat_session_id:
        query["chat_session_id"] = chat_session_id
    if event_type:
        query["event_type"] = event_type
    if actor_user_id:
        query["actor_user_id"] = str(actor_user_id)
    return query


async def query_chat_session_audits(
    agent_id: str,
    *,
    chat_session_id: str | None = None,
    event_type: str | None = None,
    actor_user_id: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Paginated audit query for future HTTP APIs.

    Uses compound indexes on agent_id + optional filters + created_at desc.
    """
    try:
        if not agent_id:
            return {
                "success": False,
                "message": "agent_id is required",
                "audits": [],
                "total": 0,
                "page": 1,
                "limit": _clamp_audit_query_limit(limit),
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            }

        page = max(1, page)
        limit = _clamp_audit_query_limit(limit)
        query = _build_chat_session_audit_query(
            agent_id,
            chat_session_id=chat_session_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
        )

        collection = get_collection(AUDIT_COLLECTION)
        total = await collection.count_documents(query)
        if total == 0:
            return {
                "success": True,
                "audits": [],
                "total": 0,
                "page": 1,
                "limit": limit,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            }

        total_pages = (total + limit - 1) // limit
        page = min(page, total_pages)
        skip = (page - 1) * limit

        cursor = (
            collection.find(query, {"_id": 0})
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        audits = [
            row
            for doc in docs
            if doc and (row := serialize_chat_session_audit(doc)) is not None
        ]

        return {
            "success": True,
            "audits": audits,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

    except Exception as e:
        logger.error(
            f"Failed to query chat session audits for agent {agent_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "message": "Failed to fetch chat session audits",
            "audits": [],
            "total": 0,
            "page": max(1, page),
            "limit": _clamp_audit_query_limit(limit),
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
        }


async def get_chat_session_audit_by_audit_id(
    agent_id: str,
    audit_id: str,
) -> dict[str, Any] | None:
    """Single audit row lookup by audit_id (unique index)."""
    try:
        if not agent_id or not audit_id:
            return None

        collection = get_collection(AUDIT_COLLECTION)
        doc = await collection.find_one(
            {"agent_id": agent_id, "audit_id": audit_id},
            {"_id": 0},
        )
        return serialize_chat_session_audit(doc)

    except Exception as e:
        logger.error(
            f"Failed to fetch audit {audit_id} for agent {agent_id}: {e}",
            exc_info=True,
        )
        return None


async def get_chat_session_audits(
    agent_id: str,
    chat_session_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch lifecycle audit rows for a session, newest first (non-paginated convenience)."""
    result = await query_chat_session_audits(
        agent_id,
        chat_session_id=chat_session_id,
        page=1,
        limit=limit,
    )
    return result.get("audits") or []

