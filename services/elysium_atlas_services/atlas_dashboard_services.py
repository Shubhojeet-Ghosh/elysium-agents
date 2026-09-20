from __future__ import annotations

import asyncio
import datetime
from typing import Any

from config.atlas_dashboard_models import (
    DASHBOARD_GRANULARITY_DAY,
    DASHBOARD_GRANULARITY_MONTH,
    DASHBOARD_RANGE_SPECS,
)
from logging_config import get_logger
from services.elysium_atlas_services.atlas_chat_session_services import (
    format_utc_datetime_for_client,
)
from services.mongo_services import get_collection

logger = get_logger()

CHAT_SESSIONS_COLLECTION = "atlas_chat_sessions"
CHAT_MESSAGES_COLLECTION = "atlas_chat_mesages"
AGENTS_COLLECTION = "atlas_agents"
VISITOR_MESSAGE_ROLE = "user"

_DATE_FORMAT_BY_GRANULARITY = {
    DASHBOARD_GRANULARITY_DAY: "%Y-%m-%d",
    DASHBOARD_GRANULARITY_MONTH: "%Y-%m",
}


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _utc_day_start(value: datetime.datetime) -> datetime.datetime:
    utc_value = value.astimezone(datetime.timezone.utc)
    return datetime.datetime(
        utc_value.year,
        utc_value.month,
        utc_value.day,
        tzinfo=datetime.timezone.utc,
    )


def _utc_month_start(value: datetime.datetime) -> datetime.datetime:
    utc_value = value.astimezone(datetime.timezone.utc)
    return datetime.datetime(
        utc_value.year,
        utc_value.month,
        1,
        tzinfo=datetime.timezone.utc,
    )


def _add_utc_months(month_start: datetime.datetime, months: int) -> datetime.datetime:
    month_index = month_start.month - 1 + months
    year = month_start.year + month_index // 12
    month = month_index % 12 + 1
    return datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)


def resolve_dashboard_date_window(
    date_range: str,
    *,
    now: datetime.datetime | None = None,
) -> tuple[datetime.datetime, datetime.datetime, str]:
    """
    Return inclusive start, exclusive end (UTC), and bucket granularity.

    Daily ranges include the current UTC calendar day. last_365_days is the
    current UTC month plus the previous 11 months (12 monthly bars).
    """
    spec = DASHBOARD_RANGE_SPECS[date_range]
    granularity = str(spec["granularity"])
    bucket_count = int(spec["bucket_count"])
    current = now or _utc_now()

    if granularity == DASHBOARD_GRANULARITY_MONTH:
        current_month_start = _utc_month_start(current)
        end_at = _add_utc_months(current_month_start, 1)
        start_at = _add_utc_months(end_at, -bucket_count)
        return start_at, end_at, granularity

    today_start = _utc_day_start(current)
    end_at = today_start + datetime.timedelta(days=1)
    start_at = end_at - datetime.timedelta(days=bucket_count)
    return start_at, end_at, granularity


def _bucket_keys_in_window(
    start_at: datetime.datetime,
    end_at: datetime.datetime,
    granularity: str,
) -> list[str]:
    date_format = _DATE_FORMAT_BY_GRANULARITY[granularity]
    keys: list[str] = []
    cursor = start_at
    while cursor < end_at:
        keys.append(cursor.strftime(date_format))
        if granularity == DASHBOARD_GRANULARITY_MONTH:
            cursor = _add_utc_months(cursor, 1)
        else:
            cursor += datetime.timedelta(days=1)
    return keys


def _agent_match(agent_ids: list[str]) -> dict[str, Any]:
    if len(agent_ids) == 1:
        return {"agent_id": agent_ids[0]}
    return {"agent_id": {"$in": agent_ids}}


async def _agent_ids_for_team(team_id: str) -> list[str]:
    collection = get_collection(AGENTS_COLLECTION)
    cursor = collection.find({"team_id": str(team_id)}, {"_id": 1})
    return [str(doc["_id"]) async for doc in cursor]


async def _count_documents_by_bucket(
    collection_name: str,
    match: dict[str, Any],
    granularity: str,
) -> dict[str, int]:
    pipeline: list[dict[str, Any]] = [
        {"$match": match},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": _DATE_FORMAT_BY_GRANULARITY[granularity],
                        "date": "$created_at",
                        "timezone": "UTC",
                    }
                },
                "count": {"$sum": 1},
            }
        },
    ]

    collection = get_collection(collection_name)
    grouped: dict[str, int] = {}
    async for doc in collection.aggregate(pipeline):
        date_key = doc.get("_id")
        if not date_key:
            continue
        grouped[str(date_key)] = int(doc.get("count") or 0)
    return grouped


def _series_payload(
    date_range: str,
    start_at: datetime.datetime,
    end_at: datetime.datetime,
    granularity: str,
    agent_id: str | None,
    session_counts: dict[str, int],
    visitor_message_counts: dict[str, int],
) -> dict[str, Any]:
    points = []
    total_sessions = 0
    total_visitor_messages = 0
    for date_key in _bucket_keys_in_window(start_at, end_at, granularity):
        session_count = session_counts.get(date_key, 0)
        visitor_message_count = visitor_message_counts.get(date_key, 0)
        total_sessions += session_count
        total_visitor_messages += visitor_message_count
        points.append(
            {
                "date": date_key,
                "count": session_count,
                "visitor_message_count": visitor_message_count,
            }
        )

    return {
        "range": date_range,
        "timezone": "UTC",
        "granularity": granularity,
        "agent_id": agent_id,
        "start_at": format_utc_datetime_for_client(start_at),
        "end_at": format_utc_datetime_for_client(end_at),
        "total": total_sessions,
        "total_visitor_messages": total_visitor_messages,
        "points": points,
    }


async def get_chat_session_counts(
    team_id: str,
    date_range: str,
    *,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """
    Count new sessions and visitor messages per UTC day or month.

    Sessions use atlas_chat_sessions.created_at (including sessions with no
    visitor message). Visitor messages use atlas_chat_mesages with role=user
    and the message created_at, including messages on older sessions.
    """
    start_at, end_at, granularity = resolve_dashboard_date_window(date_range)

    if agent_id:
        agent_ids = [agent_id]
    else:
        agent_ids = await _agent_ids_for_team(team_id)

    if not agent_ids:
        return _series_payload(
            date_range,
            start_at,
            end_at,
            granularity,
            agent_id,
            {},
            {},
        )

    time_match = {
        **_agent_match(agent_ids),
        "created_at": {"$gte": start_at, "$lt": end_at},
    }
    visitor_match = {**time_match, "role": VISITOR_MESSAGE_ROLE}

    session_counts, visitor_message_counts = await asyncio.gather(
        _count_documents_by_bucket(CHAT_SESSIONS_COLLECTION, time_match, granularity),
        _count_documents_by_bucket(CHAT_MESSAGES_COLLECTION, visitor_match, granularity),
    )

    payload = _series_payload(
        date_range,
        start_at,
        end_at,
        granularity,
        agent_id,
        session_counts,
        visitor_message_counts,
    )

    logger.info(
        "Dashboard chat session counts team_id=%s agent_id=%s range=%s "
        "granularity=%s start_at=%s end_at=%s total=%s total_visitor_messages=%s "
        "buckets=%s",
        team_id,
        agent_id,
        date_range,
        granularity,
        start_at.isoformat(),
        end_at.isoformat(),
        payload["total"],
        payload["total_visitor_messages"],
        len(payload["points"]),
    )
    return payload
