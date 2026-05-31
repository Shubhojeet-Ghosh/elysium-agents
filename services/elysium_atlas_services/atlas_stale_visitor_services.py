"""
Sweep stale visitors from Redis and mark them offline in MongoDB.

Intended to be invoked periodically (cron, background task, admin endpoint, etc.).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from logging_config import get_logger
from services.elysium_atlas_services.atlas_chat_session_services import set_visitor_online_status
from services.elysium_atlas_services.atlas_redis_services import (
    get_or_cache_agent_data_async,
    get_visitor_count_for_agent,
    iter_all_agent_visitor_entries,
    remove_visitor_from_agent,
)
from services.mongo_services import get_collection

logger = get_logger()


def get_stale_visitor_threshold_seconds() -> int:
    """Configured inactivity window before a visitor is treated as stale."""
    config = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("visitor_presence_config", {})
    return int(config.get("stale_visitor_threshold_seconds", 1800))


def _parse_timestamp(value: Any) -> datetime.datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc)

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.datetime.fromisoformat(normalized)
        except ValueError:
            logger.warning(f"Could not parse timestamp: {value!r}")
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)

    return None


def resolve_visitor_last_activity_at(
    last_message_at: Any,
    last_connected_at: Any,
    *,
    fallback: Any = None,
) -> datetime.datetime | None:
    """
    Most recent activity timestamp for stale checks.

    Considers last_message_at when set, last_connected_at, then optional fallback
    (e.g. Redis created_at). Uses the latest parsed value so a fresh reconnect
    is not treated as stale because of an older last_message_at.
    """
    candidates: List[datetime.datetime] = []
    for value in (last_message_at, last_connected_at, fallback):
        if value is None:
            continue
        parsed = _parse_timestamp(value)
        if parsed is not None:
            candidates.append(parsed)

    if not candidates:
        return None
    return max(candidates)


def is_visitor_stale(
    last_activity_at: datetime.datetime | None,
    *,
    threshold_seconds: int,
    now: datetime.datetime | None = None,
) -> bool:
    if last_activity_at is None:
        return True

    now = now or datetime.datetime.now(datetime.timezone.utc)
    age_seconds = (now - last_activity_at).total_seconds()
    return age_seconds > threshold_seconds


async def _fetch_session_activity_fields(
    agent_id: str,
    chat_session_id: str,
) -> Dict[str, Any] | None:
    collection = get_collection("atlas_chat_sessions")
    return await collection.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
        {"last_message_at": 1, "last_connected_at": 1, "visitor_online": 1, "_id": 0},
    )


async def _emit_stale_visitor_events(
    cleaned_by_agent: Dict[str, List[Tuple[str, str | None]]],
) -> None:
    """Emit the same socket events as a normal visitor disconnect."""
    if not cleaned_by_agent:
        return

    from sockets import sio

    for agent_id, disconnects in cleaned_by_agent.items():
        agent_members_room = f"agent_{agent_id}_members"

        for sid, chat_session_id in disconnects:
            await sio.emit(
                "agent_visitor_disconnected",
                {"agent_id": agent_id, "chat_session_id": chat_session_id, "sid": sid},
                room=agent_members_room,
            )

        agent_data = await get_or_cache_agent_data_async(agent_id)
        if not agent_data:
            continue

        team_id = agent_data.get("team_id")
        if not team_id:
            continue

        visitor_count = get_visitor_count_for_agent(agent_id)
        team_room = f"team_{team_id}_members"
        await sio.emit(
            "agent_visitor_count_updated",
            {
                "agent_id": agent_id,
                "visitor_count": visitor_count if visitor_count is not None else 0,
            },
            room=team_room,
        )
        logger.info(
            f"Emitted stale cleanup events for agent {agent_id}: "
            f"removed {len(disconnects)} visitor(s), count={visitor_count}"
        )


async def cleanup_stale_visitors_service(
    *,
    threshold_seconds: int | None = None,
    emit_events: bool = True,
) -> Dict[str, Any]:
    """
    Scan all connected visitors across all agents and remove stale entries.

    A visitor is stale when its last activity is older than the configured threshold.
    Last activity is the most recent of last_message_at and last_connected_at
    (Mongo first, Redis visitor payload as fallback for missing fields).

    Args:
        threshold_seconds: Override for stale_visitor_threshold_seconds config.
        emit_events: When True, emit agent_visitor_disconnected and
            agent_visitor_count_updated socket events (default True).

    Returns:
        Summary dict with success and cleaned_count.
    """
    threshold = threshold_seconds if threshold_seconds is not None else get_stale_visitor_threshold_seconds()
    now = datetime.datetime.now(datetime.timezone.utc)
    cleaned_count = 0
    cleaned_by_agent: Dict[str, List[Tuple[str, str | None]]] = defaultdict(list)
    scanned = 0
    errors = 0

    try:
        for agent_id, sid, visitor_data in iter_all_agent_visitor_entries():
            scanned += 1
            chat_session_id = visitor_data.get("chat_session_id")

            try:
                session_doc = None
                if chat_session_id:
                    session_doc = await _fetch_session_activity_fields(agent_id, chat_session_id)

                last_message_at = session_doc.get("last_message_at") if session_doc else None
                last_connected_at = session_doc.get("last_connected_at") if session_doc else None

                if last_connected_at is None:
                    last_connected_at = visitor_data.get("last_connected_at")

                fallback = visitor_data.get("created_at")
                last_activity_at = resolve_visitor_last_activity_at(
                    last_message_at,
                    last_connected_at,
                    fallback=fallback,
                )

                if not is_visitor_stale(last_activity_at, threshold_seconds=threshold, now=now):
                    continue

                remove_visitor_from_agent(agent_id, sid)

                if chat_session_id:
                    await set_visitor_online_status(agent_id, chat_session_id, False)

                cleaned_count += 1
                cleaned_by_agent[agent_id].append((sid, chat_session_id))
                logger.info(
                    f"Removed stale visitor sid={sid} agent_id={agent_id} "
                    f"chat_session_id={chat_session_id} last_activity_at={last_activity_at}"
                )
            except Exception as e:
                errors += 1
                logger.error(
                    f"Error cleaning stale visitor sid={sid} agent_id={agent_id}: {e}"
                )

        if emit_events and cleaned_by_agent:
            await _emit_stale_visitor_events(cleaned_by_agent)

        summary = {
            "success": True,
            "cleaned_count": cleaned_count,
        }
        logger.info(
            f"Stale visitor cleanup complete: scanned={scanned} cleaned={cleaned_count} "
            f"errors={errors} threshold_seconds={threshold}"
        )
        return summary

    except Exception as e:
        logger.error(f"Stale visitor cleanup failed: {e}")
        return {
            "success": False,
            "message": str(e),
            "cleaned_count": cleaned_count,
        }
