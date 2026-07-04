"""
Mongo-backed live presence for Atlas visitors and team members.

Visitors: atlas_chat_sessions (visitor_online, last_connected_at, …) — no socket ids in Mongo
Team members: atlas_team_member_presence (one doc per user + team; durable presence only)
Visitor socket routing: atlas_visitor_socket_rooms.py (per chat_session Socket.IO room)
Team member socket routing: atlas_team_member_socket_rooms.py (per-user Socket.IO room)
"""

from __future__ import annotations

import datetime
from typing import Any

from logging_config import get_logger
from services.mongo_services import get_collection

logger = get_logger()

TEAM_MEMBER_PRESENCE_COLLECTION = "atlas_team_member_presence"


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _serialize_dt(value: Any) -> str | None:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value if value is not None else None


def session_doc_to_live_visitor(session_doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a live-visitor payload from an atlas_chat_sessions document."""
    if not session_doc or not session_doc.get("visitor_online"):
        return None

    return {
        "agent_id": session_doc.get("agent_id"),
        "chat_session_id": session_doc.get("chat_session_id"),
        "in_conversation_with": session_doc.get("in_conversation_with"),
        "alias_name": session_doc.get("alias_name"),
        "geo_data": session_doc.get("geo_data"),
        "visitor_at": session_doc.get("visitor_at"),
        "last_connected_at": _serialize_dt(session_doc.get("last_connected_at")),
        "last_message_at": _serialize_dt(session_doc.get("last_message_at")),
        "created_at": _serialize_dt(session_doc.get("created_at")),
    }


async def is_visitor_online(agent_id: str, chat_session_id: str) -> bool:
    if not agent_id or not chat_session_id:
        return False
    collection = get_collection("atlas_chat_sessions")
    doc = await collection.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id, "visitor_online": True},
        {"_id": 1},
    )
    return doc is not None


async def connect_visitor_presence(
    agent_id: str,
    chat_session_id: str,
    *,
    geo_data: dict | None = None,
    visitor_at: str | None = None,
    alias_name: str | None = None,
) -> dict[str, Any] | None:
    """Mark a visitor online on their chat session document (durable presence only)."""
    if not agent_id or not chat_session_id:
        return None

    now = _utc_now()
    collection = get_collection("atlas_chat_sessions")

    set_fields: dict[str, Any] = {
        "visitor_online": True,
        "last_connected_at": now,
    }
    if geo_data is not None:
        set_fields["geo_data"] = geo_data
    if visitor_at is not None:
        set_fields["visitor_at"] = visitor_at
    if alias_name is not None:
        set_fields["alias_name"] = alias_name

    await collection.update_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
        {"$set": set_fields},
    )

    doc = await collection.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
    )
    return session_doc_to_live_visitor(doc)


async def disconnect_visitor_presence(
    agent_id: str,
    chat_session_id: str,
    sid: str,
) -> tuple[bool, str | None]:
    """
    Mark visitor offline when no other socket remains in the session room.

    Returns (was_removed, chat_session_id).
    """
    from services.elysium_atlas_services.atlas_visitor_socket_rooms import (
        visitor_session_room_has_connections,
    )

    if not agent_id or not chat_session_id or not sid:
        return False, chat_session_id or None

    if await visitor_session_room_has_connections(chat_session_id, exclude_sid=sid):
        return False, chat_session_id

    collection = get_collection("atlas_chat_sessions")
    result = await collection.update_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id, "visitor_online": True},
        {"$set": {"visitor_online": False}},
    )
    if result.modified_count == 0:
        return False, chat_session_id
    return True, chat_session_id


async def mark_visitor_offline(agent_id: str, chat_session_id: str) -> bool:
    """Force visitor offline in Mongo (stale cleanup)."""
    if not agent_id or not chat_session_id:
        return False
    collection = get_collection("atlas_chat_sessions")
    result = await collection.update_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
        {"$set": {"visitor_online": False}},
    )
    return result.modified_count > 0


async def get_visitor_by_chat_session(agent_id: str, chat_session_id: str) -> dict[str, Any] | None:
    if not agent_id or not chat_session_id:
        return None
    collection = get_collection("atlas_chat_sessions")
    doc = await collection.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id, "visitor_online": True},
    )
    return session_doc_to_live_visitor(doc)


async def get_visitor_count_for_agent(agent_id: str) -> int:
    if not agent_id:
        return 0
    collection = get_collection("atlas_chat_sessions")
    return await collection.count_documents({"agent_id": agent_id, "visitor_online": True})


async def get_online_visitors_map_by_chat_session(agent_id: str) -> dict[str, dict]:
    if not agent_id:
        return {}
    collection = get_collection("atlas_chat_sessions")
    cursor = collection.find(
        {"agent_id": agent_id, "visitor_online": True},
        {
            "chat_session_id": 1,
            "in_conversation_with": 1,
            "alias_name": 1,
            "geo_data": 1,
            "visitor_at": 1,
            "last_connected_at": 1,
            "last_message_at": 1,
            "created_at": 1,
            "agent_id": 1,
        },
    )
    result: dict[str, dict] = {}
    async for doc in cursor:
        chat_session_id = doc.get("chat_session_id")
        if not chat_session_id:
            continue
        live = session_doc_to_live_visitor(doc)
        if live:
            result[chat_session_id] = live
    return result


async def update_visitor_conversation_status(
    agent_id: str,
    chat_session_id: str,
    user_id: str | None,
) -> bool:
    """Update in_conversation_with on the session doc; return True when visitor is online."""
    if not agent_id or not chat_session_id:
        return False

    collection = get_collection("atlas_chat_sessions")
    doc = await collection.find_one_and_update(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
        {"$set": {"in_conversation_with": user_id}},
        projection={"visitor_online": 1},
        return_document=True,
    )
    return bool(doc and doc.get("visitor_online"))


async def iter_online_visitor_sessions() -> list[tuple[str, str, dict[str, Any]]]:
    """
    Return (agent_id, chat_session_id, visitor_data) for every online visitor (stale cleanup).
    """
    collection = get_collection("atlas_chat_sessions")
    cursor = collection.find(
        {"visitor_online": True},
        {
            "agent_id": 1,
            "chat_session_id": 1,
            "last_connected_at": 1,
            "last_message_at": 1,
            "created_at": 1,
        },
    )
    entries: list[tuple[str, str, dict[str, Any]]] = []
    async for doc in cursor:
        agent_id = doc.get("agent_id")
        chat_session_id = doc.get("chat_session_id")
        if not agent_id or not chat_session_id:
            continue
        live = session_doc_to_live_visitor(doc)
        if live:
            entries.append((agent_id, chat_session_id, live))
    return entries


# ---------------------------------------------------------------------------
# Team member presence (atlas_team_member_presence) — durable only, no socket ids
# ---------------------------------------------------------------------------


def _team_presence_filter(user_id: str, team_id: str) -> dict[str, Any]:
    return {"user_id": str(user_id), "team_id": str(team_id)}


async def register_team_member_presence(
    team_id: str,
    user_id: str,
    *,
    agent_id: str | None = None,
) -> bool:
    """Upsert one presence doc per (user_id, team_id); optionally track an active agent."""
    if not team_id or not user_id:
        return False

    now = _utc_now()
    collection = get_collection(TEAM_MEMBER_PRESENCE_COLLECTION)
    filt = _team_presence_filter(user_id, team_id)

    update: dict[str, Any] = {
        "$set": {
            "status": "online",
            "last_seen_at": now,
        },
        "$setOnInsert": {
            "connected_at": now,
        },
    }
    if agent_id:
        update["$addToSet"] = {"active_agent_ids": str(agent_id)}
    else:
        update["$setOnInsert"]["active_agent_ids"] = []

    await collection.update_one(filt, update, upsert=True)
    return True


async def remove_team_member_active_agent(
    team_id: str,
    user_id: str,
    agent_id: str,
) -> None:
    """Leave agent scope only; team-level online status is preserved."""
    if not team_id or not user_id or not agent_id:
        return

    collection = get_collection(TEAM_MEMBER_PRESENCE_COLLECTION)
    await collection.update_one(
        _team_presence_filter(user_id, team_id),
        {
            "$pull": {"active_agent_ids": str(agent_id)},
            "$set": {"last_seen_at": _utc_now()},
        },
    )


async def set_team_member_offline(team_id: str | None, user_id: str) -> list[str]:
    """
    Mark atlas_team_member_presence offline and clear active_agent_ids.

    Returns prior active_agent_ids (for session-monitor cleanup on disconnect).
    """
    if not user_id:
        return []

    collection = get_collection(TEAM_MEMBER_PRESENCE_COLLECTION)
    filt = (
        _team_presence_filter(user_id, team_id)
        if team_id
        else {"user_id": str(user_id), "status": "online"}
    )
    now = _utc_now()

    doc = await collection.find_one_and_update(
        filt,
        {
            "$set": {
                "status": "offline",
                "active_agent_ids": [],
                "last_seen_at": now,
            }
        },
        projection={"active_agent_ids": 1, "team_id": 1},
    )
    if not doc:
        return []

    resolved_team_id = team_id or doc.get("team_id")
    logger.info(
        f"Marked team member offline in Mongo: user_id={user_id} team_id={resolved_team_id}"
    )
    return [str(a) for a in (doc.get("active_agent_ids") or []) if a]


async def is_team_member_online_for_agent(agent_id: str, user_id: str) -> bool:
    if not agent_id or not user_id:
        return False
    collection = get_collection(TEAM_MEMBER_PRESENCE_COLLECTION)
    doc = await collection.find_one(
        {
            "user_id": str(user_id),
            "status": "online",
            "active_agent_ids": str(agent_id),
        },
        {"_id": 1},
    )
    return doc is not None


async def has_connected_team_members_for_agent(agent_id: str) -> bool:
    if not agent_id:
        return False
    collection = get_collection(TEAM_MEMBER_PRESENCE_COLLECTION)
    count = await collection.count_documents(
        {"status": "online", "active_agent_ids": str(agent_id)},
    )
    return count > 0


async def get_agent_ids_for_user_in_team(team_id: str, user_id: str) -> list[str]:
    if not team_id or not user_id:
        return []
    collection = get_collection(TEAM_MEMBER_PRESENCE_COLLECTION)
    doc = await collection.find_one(
        {**_team_presence_filter(user_id, team_id), "status": "online"},
        {"active_agent_ids": 1},
    )
    if not doc:
        return []
    return [str(a) for a in (doc.get("active_agent_ids") or []) if a]


async def remove_team_member_presence(team_id: str, user_id: str) -> None:
    """Full team logout — mark offline and clear active agents."""
    await set_team_member_offline(team_id, user_id)


async def remove_session_monitors_for_user_on_agent(
    agent_id: str,
    user_id: str,
    sid: str | None = None,
) -> None:
    """Delegate to Redis session monitors (ephemeral socket routing)."""
    from services.elysium_atlas_services.atlas_redis_services import (
        remove_all_session_monitors_for_user,
    )

    remove_all_session_monitors_for_user(agent_id, user_id, sid=sid)
