"""
Tool calling orchestration settings for atlas agents (multi-round HTTP tool execution).
Extend ALLOWED_TOOL_CALLING_FIELDS and FIELD_VALIDATORS when adding new keys.
"""

from config.atlas_tool_config import (
    ABSOLUTE_MAX_TOOL_EXECUTIONS_PER_TURN,
    ABSOLUTE_MAX_TOOL_ROUNDS,
)

ENABLED_KEY = "enabled"
MAX_ROUNDS_KEY = "max_rounds"
MAX_EXECUTIONS_PER_TURN_KEY = "max_executions_per_turn"
PARALLEL_CALLS_PER_ROUND_KEY = "parallel_calls_per_round"
STOP_ON_ERROR_KEY = "stop_on_error"

DEFAULT_MAX_ROUNDS = 5
DEFAULT_MAX_EXECUTIONS_PER_TURN = 10

MAX_ROUNDS_MIN = 1
MAX_EXECUTIONS_PER_TURN_MIN = 1

DEFAULT_TOOL_CALLING_CONFIG: dict = {
    ENABLED_KEY: True,
    MAX_ROUNDS_KEY: DEFAULT_MAX_ROUNDS,
    MAX_EXECUTIONS_PER_TURN_KEY: DEFAULT_MAX_EXECUTIONS_PER_TURN,
    PARALLEL_CALLS_PER_ROUND_KEY: True,
    STOP_ON_ERROR_KEY: False,
}

ALLOWED_TOOL_CALLING_FIELDS = frozenset(DEFAULT_TOOL_CALLING_CONFIG.keys())


def get_default_tool_calling_config() -> dict:
    return dict(DEFAULT_TOOL_CALLING_CONFIG)


def _validate_enabled(value) -> tuple[bool, str | None]:
    if not isinstance(value, bool):
        return False, f"{ENABLED_KEY} must be a boolean."
    return True, None


def _validate_max_rounds(value) -> tuple[bool, str | None]:
    if not isinstance(value, int) or isinstance(value, bool):
        return False, f"{MAX_ROUNDS_KEY} must be an integer."

    if value < MAX_ROUNDS_MIN or value > ABSOLUTE_MAX_TOOL_ROUNDS:
        return (
            False,
            f"{MAX_ROUNDS_KEY} must be between {MAX_ROUNDS_MIN} and {ABSOLUTE_MAX_TOOL_ROUNDS}.",
        )
    return True, None


def _validate_max_executions_per_turn(value) -> tuple[bool, str | None]:
    if not isinstance(value, int) or isinstance(value, bool):
        return False, f"{MAX_EXECUTIONS_PER_TURN_KEY} must be an integer."

    if value < MAX_EXECUTIONS_PER_TURN_MIN or value > ABSOLUTE_MAX_TOOL_EXECUTIONS_PER_TURN:
        return (
            False,
            f"{MAX_EXECUTIONS_PER_TURN_KEY} must be between "
            f"{MAX_EXECUTIONS_PER_TURN_MIN} and {ABSOLUTE_MAX_TOOL_EXECUTIONS_PER_TURN}.",
        )
    return True, None


def _validate_parallel_calls_per_round(value) -> tuple[bool, str | None]:
    if not isinstance(value, bool):
        return False, f"{PARALLEL_CALLS_PER_ROUND_KEY} must be a boolean."
    return True, None


def _validate_stop_on_error(value) -> tuple[bool, str | None]:
    if not isinstance(value, bool):
        return False, f"{STOP_ON_ERROR_KEY} must be a boolean."
    return True, None


FIELD_VALIDATORS = {
    ENABLED_KEY: _validate_enabled,
    MAX_ROUNDS_KEY: _validate_max_rounds,
    MAX_EXECUTIONS_PER_TURN_KEY: _validate_max_executions_per_turn,
    PARALLEL_CALLS_PER_ROUND_KEY: _validate_parallel_calls_per_round,
    STOP_ON_ERROR_KEY: _validate_stop_on_error,
}


def normalize_tool_calling_config(config: dict | None) -> dict:
    """Return a normalized copy of a full tool_calling_config object."""
    normalized = get_default_tool_calling_config()
    if not isinstance(config, dict):
        return normalized

    for key in ALLOWED_TOOL_CALLING_FIELDS:
        if key in config and config[key] is not None:
            normalized[key] = config[key]

    return normalized


def validate_tool_calling_config(config) -> tuple[bool, str | None]:
    """
    Validate a tool_calling_config object (full or partial).

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(config, dict):
        return False, "tool_calling_config must be an object."

    invalid = set(config.keys()) - ALLOWED_TOOL_CALLING_FIELDS
    if invalid:
        allowed = ", ".join(sorted(ALLOWED_TOOL_CALLING_FIELDS))
        return False, f"Invalid tool_calling_config field(s): {invalid}. Allowed: {allowed}."

    for key, value in config.items():
        if value is None:
            continue
        is_valid, error_message = FIELD_VALIDATORS[key](value)
        if not is_valid:
            return False, error_message

    return True, None


def build_tool_calling_config_for_create(override: dict | None = None) -> tuple[dict, str | None]:
    """
    Build tool_calling_config for new agents, starting from defaults.

    Returns:
        (config, error_message)
    """
    config = get_default_tool_calling_config()
    if override is None:
        return config, None

    is_valid, error_message = validate_tool_calling_config(override)
    if not is_valid:
        return get_default_tool_calling_config(), error_message

    config.update(override)
    return normalize_tool_calling_config(config), None


def merge_tool_calling_config(
    existing: dict | None,
    partial: dict,
) -> tuple[dict, str | None]:
    """
    Merge a partial tool_calling_config into the stored config.

    Returns:
        (merged_config, error_message)
    """
    is_valid, error_message = validate_tool_calling_config(partial)
    if not is_valid:
        return get_default_tool_calling_config(), error_message

    merged = get_default_tool_calling_config()
    if isinstance(existing, dict):
        merged = normalize_tool_calling_config(existing)

    for key, value in partial.items():
        if value is not None:
            merged[key] = value

    return normalize_tool_calling_config(merged), None
