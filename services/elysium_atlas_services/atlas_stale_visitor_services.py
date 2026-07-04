"""
Sweep stale visitors from Mongo and mark them offline.

Intended to be invoked periodically (cron, background task, admin endpoint, etc.).
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from logging_config import get_logger
from services.elysium_atlas_services.atlas_presence_services import (
    iter_online_visitor_sessions,
    mark_visitor_offline,
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
    (e.g. session created_at). Uses the latest parsed value so a fresh reconnect
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


async def cleanup_stale_visitors_service(
    *,
    threshold_seconds: int | None = None,
) -> Dict[str, Any]:
    """
    Scan all connected visitors across all agents and remove stale entries.

    A visitor is stale when its last activity is older than the configured threshold.
    Last activity is the most recent of last_message_at and last_connected_at on the session doc.

    Args:
        threshold_seconds: Override for stale_visitor_threshold_seconds config.

    Returns:
        Summary dict with success and cleaned_count.
    """
    threshold = threshold_seconds if threshold_seconds is not None else get_stale_visitor_threshold_seconds()
    now = datetime.datetime.now(datetime.timezone.utc)
    cleaned_count = 0
    scanned = 0
    errors = 0

    try:
        online_entries = await iter_online_visitor_sessions()
        for agent_id, chat_session_id, visitor_data in online_entries:
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

                await mark_visitor_offline(agent_id, chat_session_id)

                cleaned_count += 1
                logger.info(
                    f"Removed stale visitor agent_id={agent_id} "
                    f"chat_session_id={chat_session_id} last_activity_at={last_activity_at}"
                )
            except Exception as e:
                errors += 1
                logger.error(
                    f"Error cleaning stale visitor agent_id={agent_id} "
                    f"chat_session_id={chat_session_id}: {e}"
                )

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
