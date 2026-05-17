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
