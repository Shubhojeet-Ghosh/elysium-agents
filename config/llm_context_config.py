"""
LLM prompt context settings for atlas agents (chat history window for main agent LLM).
Extend ALLOWED_LLM_CONTEXT_FIELDS and FIELD_VALIDATORS when adding new keys.
"""

MAX_CHAT_HISTORY_MESSAGES_KEY = "max_chat_history_messages"

DEFAULT_MAX_CHAT_HISTORY_MESSAGES = 10
MAX_CHAT_HISTORY_MESSAGES_MIN = 1
ABSOLUTE_MAX_CHAT_HISTORY_MESSAGES = 100

DEFAULT_LLM_CONTEXT_CONFIG: dict = {
    MAX_CHAT_HISTORY_MESSAGES_KEY: DEFAULT_MAX_CHAT_HISTORY_MESSAGES,
}

ALLOWED_LLM_CONTEXT_FIELDS = frozenset(DEFAULT_LLM_CONTEXT_CONFIG.keys())


def get_default_llm_context_config() -> dict:
    return dict(DEFAULT_LLM_CONTEXT_CONFIG)


def _validate_max_chat_history_messages(value) -> tuple[bool, str | None]:
    if not isinstance(value, int) or isinstance(value, bool):
        return False, f"{MAX_CHAT_HISTORY_MESSAGES_KEY} must be an integer."

    if value < MAX_CHAT_HISTORY_MESSAGES_MIN or value > ABSOLUTE_MAX_CHAT_HISTORY_MESSAGES:
        return (
            False,
            f"{MAX_CHAT_HISTORY_MESSAGES_KEY} must be between "
            f"{MAX_CHAT_HISTORY_MESSAGES_MIN} and {ABSOLUTE_MAX_CHAT_HISTORY_MESSAGES}.",
        )
    return True, None


FIELD_VALIDATORS = {
    MAX_CHAT_HISTORY_MESSAGES_KEY: _validate_max_chat_history_messages,
}


def normalize_llm_context_config(config: dict | None) -> dict:
    """Return a normalized copy of a full llm_context_config object."""
    normalized = get_default_llm_context_config()
    if not isinstance(config, dict):
        return normalized

    for key in ALLOWED_LLM_CONTEXT_FIELDS:
        if key in config and config[key] is not None:
            normalized[key] = config[key]

    return normalized


def validate_llm_context_config(config) -> tuple[bool, str | None]:
    """
    Validate an llm_context_config object (full or partial).

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(config, dict):
        return False, "llm_context_config must be an object."

    invalid = set(config.keys()) - ALLOWED_LLM_CONTEXT_FIELDS
    if invalid:
        allowed = ", ".join(sorted(ALLOWED_LLM_CONTEXT_FIELDS))
        return False, f"Invalid llm_context_config field(s): {invalid}. Allowed: {allowed}."

    for key, value in config.items():
        if value is None:
            continue
        is_valid, error_message = FIELD_VALIDATORS[key](value)
        if not is_valid:
            return False, error_message

    return True, None


def build_llm_context_config_for_create(override: dict | None = None) -> tuple[dict, str | None]:
    """
    Build llm_context_config for new agents, starting from defaults.

    Returns:
        (config, error_message)
    """
    config = get_default_llm_context_config()
    if override is None:
        return config, None

    is_valid, error_message = validate_llm_context_config(override)
    if not is_valid:
        return get_default_llm_context_config(), error_message

    config.update(override)
    return normalize_llm_context_config(config), None


def merge_llm_context_config(
    existing: dict | None,
    partial: dict,
) -> tuple[dict, str | None]:
    """
    Merge a partial llm_context_config into the stored config.

    Returns:
        (merged_config, error_message)
    """
    is_valid, error_message = validate_llm_context_config(partial)
    if not is_valid:
        return get_default_llm_context_config(), error_message

    merged = get_default_llm_context_config()
    if isinstance(existing, dict):
        merged = normalize_llm_context_config(existing)

    for key, value in partial.items():
        if value is not None:
            merged[key] = value

    return normalize_llm_context_config(merged), None


def resolve_max_chat_history_messages(llm_context_config: dict | None) -> int:
    """Return the configured user/agent message window for main agent LLM prompts."""
    config = normalize_llm_context_config(llm_context_config)
    return int(config[MAX_CHAT_HISTORY_MESSAGES_KEY])
