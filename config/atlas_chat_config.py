"""
Visitor chat limits for atlas agents.

Per-user override (atlas_user_available_plan_limits):
  max_visitor_message_chars — int, optional

Fallback when the key is absent (legacy documents):
  config/atlas_agent_config_data.py → agent_chat_limits.max_visitor_message_chars
"""

from typing import Any, Dict, Optional

from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA

# Field name on atlas_user_available_plan_limits documents
PLAN_LIMIT_MAX_VISITOR_MESSAGE_CHARS_KEY = "max_visitor_message_chars"

_agent_chat_limits = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_chat_limits", {})
DEFAULT_MAX_VISITOR_MESSAGE_CHARS = int(
    _agent_chat_limits.get("max_visitor_message_chars", 4000)
)

CHAT_SESSION_STATUS_ACTIVE = "active"
CHAT_SESSION_STATUS_IN_CONVERSATION = "in_conversation"
CHAT_SESSION_STATUS_RESOLVED = "resolved"

SUPPORTED_CHAT_SESSION_STATUSES = frozenset(
    {
        CHAT_SESSION_STATUS_ACTIVE,
        CHAT_SESSION_STATUS_IN_CONVERSATION,
        CHAT_SESSION_STATUS_RESOLVED,
    }
)


def resolve_chat_session_status_for_takeover(user_id: str | None) -> str:
    """Map takeover handler presence to atlas_chat_sessions.status."""
    return CHAT_SESSION_STATUS_IN_CONVERSATION if user_id else CHAT_SESSION_STATUS_ACTIVE


def get_default_max_visitor_message_chars() -> int:
    return DEFAULT_MAX_VISITOR_MESSAGE_CHARS


def resolve_max_visitor_message_chars(plan_limits: Optional[Dict[str, Any]]) -> int:
    """
    Resolve the message length cap for a user.

    Uses plan_limits[max_visitor_message_chars] when the key is present and valid;
    otherwise falls back to DEFAULT_MAX_VISITOR_MESSAGE_CHARS (legacy documents).
    """
    if not plan_limits or PLAN_LIMIT_MAX_VISITOR_MESSAGE_CHARS_KEY not in plan_limits:
        return get_default_max_visitor_message_chars()

    value = plan_limits[PLAN_LIMIT_MAX_VISITOR_MESSAGE_CHARS_KEY]
    if value is None:
        return get_default_max_visitor_message_chars()

    try:
        parsed = int(value)
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass

    return get_default_max_visitor_message_chars()


def validate_visitor_message(
    message,
    max_chars: Optional[int] = None,
) -> tuple[bool, str | None, str | None]:
    """
    Validate a visitor chat message before LLM / retrieval work.

    Args:
        message: Visitor message from the chat payload.
        max_chars: Per-user or default character limit; uses default when None.

    Returns:
        (is_valid, internal_error_message, client_error_message)
    """
    limit = max_chars if max_chars is not None else get_default_max_visitor_message_chars()

    if message is None:
        return False, "Message is required.", "Please enter a message."

    if not isinstance(message, str):
        return False, "Message must be a string.", "Invalid message format."

    if not message.strip():
        return False, "Message cannot be empty.", "Please enter a message."

    if len(message) > limit:
        internal = (
            f"Message exceeds the maximum length of {limit} characters "
            f"(received {len(message)})."
        )
        client = "Your message is too long. Please shorten it and try again."
        return False, internal, client

    return True, None, None


CHAT_SESSION_LIST_MAX_PAGE_SIZE = 100
CHAT_SESSION_SEARCH_MAX_QUERY_CHARS = 200


def validate_chat_session_search_query(query: str | None) -> tuple[bool, str | None, str]:
    """
    Validate a team-member chat session search string.

    Returns:
        (is_valid, error_message, normalized_query)
    """
    if query is None:
        return False, "query is required.", ""

    if not isinstance(query, str):
        return False, "query must be a string.", ""

    normalized = query.strip()
    if not normalized:
        return False, "query cannot be empty.", ""

    if len(normalized) > CHAT_SESSION_SEARCH_MAX_QUERY_CHARS:
        return (
            False,
            f"query cannot exceed {CHAT_SESSION_SEARCH_MAX_QUERY_CHARS} characters.",
            normalized[:CHAT_SESSION_SEARCH_MAX_QUERY_CHARS],
        )

    return True, None, normalized


def clamp_chat_session_list_page_size(size: int | None) -> int:
    """Bound list/search page size to a safe positive maximum."""
    if size is None or size < 1:
        return 1
    return min(size, CHAT_SESSION_LIST_MAX_PAGE_SIZE)


def normalize_chat_session_refresh_ids(
    chat_session_ids: object | None,
) -> tuple[bool, str | None, list[str]]:
    """
    Validate chat_session_ids for atlas-agent-visitors-refresh-sessions.

    Dedupes, trims, and caps at CHAT_SESSION_LIST_MAX_PAGE_SIZE (100).
    """
    if chat_session_ids is None:
        return False, "chat_session_ids is required.", []

    if not isinstance(chat_session_ids, list):
        return False, "chat_session_ids must be an array.", []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in chat_session_ids:
        if not isinstance(item, str):
            continue
        session_id = item.strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        normalized.append(session_id)
        if len(normalized) >= CHAT_SESSION_LIST_MAX_PAGE_SIZE:
            break

    if not normalized:
        return False, "chat_session_ids must contain at least one valid id.", []

    return True, None, normalized
