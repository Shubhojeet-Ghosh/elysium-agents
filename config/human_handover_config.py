"""
Human handover settings for atlas agents.
"""

ENABLE_HUMAN_HANDOVER_KEY = "enable_human_handover"
HANDOVER_TRIGGER_PROMPT_KEY = "handover_trigger_prompt"

HANDOVER_TRIGGER_PROMPT_MIN_LENGTH = 10
HANDOVER_TRIGGER_PROMPT_MAX_LENGTH = 500

DEFAULT_HUMAN_HANDOVER_CONFIG: dict = {
    ENABLE_HUMAN_HANDOVER_KEY: False,
    HANDOVER_TRIGGER_PROMPT_KEY: "",
}

ALLOWED_HUMAN_HANDOVER_FIELDS = frozenset(DEFAULT_HUMAN_HANDOVER_CONFIG.keys())


def get_default_human_handover_config() -> dict:
    return dict(DEFAULT_HUMAN_HANDOVER_CONFIG)


def _validate_enable_human_handover(value) -> tuple[bool, str | None]:
    if not isinstance(value, bool):
        return False, f"{ENABLE_HUMAN_HANDOVER_KEY} must be a boolean."
    return True, None


def _validate_handover_trigger_prompt(value, *, enabled: bool) -> tuple[bool, str | None]:
    if value is None:
        if enabled:
            return False, f"{HANDOVER_TRIGGER_PROMPT_KEY} is required when human handover is enabled."
        return True, None

    if not isinstance(value, str):
        return False, f"{HANDOVER_TRIGGER_PROMPT_KEY} must be a string."

    normalized = value.strip()
    if not enabled:
        return True, None

    if len(normalized) < HANDOVER_TRIGGER_PROMPT_MIN_LENGTH:
        return (
            False,
            f"{HANDOVER_TRIGGER_PROMPT_KEY} must be at least "
            f"{HANDOVER_TRIGGER_PROMPT_MIN_LENGTH} characters when human handover is enabled.",
        )

    if len(normalized) > HANDOVER_TRIGGER_PROMPT_MAX_LENGTH:
        return (
            False,
            f"{HANDOVER_TRIGGER_PROMPT_KEY} must be at most "
            f"{HANDOVER_TRIGGER_PROMPT_MAX_LENGTH} characters.",
        )

    return True, None


def _normalize_handover_trigger_prompt(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def normalize_human_handover_config(config: dict) -> dict:
    """Return a normalized copy of a full human_handover_config object."""
    normalized = get_default_human_handover_config()
    if not isinstance(config, dict):
        return normalized

    if ENABLE_HUMAN_HANDOVER_KEY in config:
        normalized[ENABLE_HUMAN_HANDOVER_KEY] = bool(config[ENABLE_HUMAN_HANDOVER_KEY])

    if HANDOVER_TRIGGER_PROMPT_KEY in config:
        normalized[HANDOVER_TRIGGER_PROMPT_KEY] = _normalize_handover_trigger_prompt(
            config[HANDOVER_TRIGGER_PROMPT_KEY]
        )

    return normalized


def validate_human_handover_config(config, *, validate_enabled_requirements: bool = False) -> tuple[bool, str | None]:
    """
    Validate a human_handover_config object (full or partial).

    Only keys present in config are validated; use for partial updates.
    """
    if config is None:
        return True, None

    if not isinstance(config, dict):
        return False, "human_handover_config must be an object."

    unknown = set(config.keys()) - ALLOWED_HUMAN_HANDOVER_FIELDS
    if unknown:
        allowed = ", ".join(sorted(ALLOWED_HUMAN_HANDOVER_FIELDS))
        invalid = ", ".join(sorted(unknown))
        return False, (
            f"Invalid human_handover_config field(s): {invalid}. "
            f"Allowed fields: {allowed}."
        )

    if ENABLE_HUMAN_HANDOVER_KEY in config:
        is_valid, error_message = _validate_enable_human_handover(config[ENABLE_HUMAN_HANDOVER_KEY])
        if not is_valid:
            return False, error_message

    enabled = (
        bool(config.get(ENABLE_HUMAN_HANDOVER_KEY))
        if ENABLE_HUMAN_HANDOVER_KEY in config
        else False
    )

    if HANDOVER_TRIGGER_PROMPT_KEY in config:
        is_valid, error_message = _validate_handover_trigger_prompt(
            config[HANDOVER_TRIGGER_PROMPT_KEY],
            enabled=enabled if validate_enabled_requirements else False,
        )
        if not is_valid:
            return False, error_message

    return True, None


def validate_merged_human_handover_config(config: dict) -> tuple[bool, str | None]:
    """Validate a full merged human_handover_config, including enabled cross-field rules."""
    if not isinstance(config, dict):
        return False, "human_handover_config must be an object."

    is_valid, error_message = validate_human_handover_config(config)
    if not is_valid:
        return False, error_message

    normalized = normalize_human_handover_config(config)
    enabled = normalized[ENABLE_HUMAN_HANDOVER_KEY]

    is_valid, error_message = _validate_handover_trigger_prompt(
        normalized[HANDOVER_TRIGGER_PROMPT_KEY],
        enabled=enabled,
    )
    if not is_valid:
        return False, error_message

    return True, None


def build_human_handover_config_for_create(override: dict | None = None) -> tuple[dict, str | None]:
    """
    Build human_handover_config for new agents, starting from defaults.

    Returns:
        (config, error_message)
    """
    config = get_default_human_handover_config()
    if override is None:
        return config, None

    is_valid, error_message = validate_human_handover_config(override)
    if not is_valid:
        return config, error_message

    config.update(override)
    config = normalize_human_handover_config(config)

    is_valid, error_message = validate_merged_human_handover_config(config)
    if not is_valid:
        return get_default_human_handover_config(), error_message

    return config, None


def merge_human_handover_config(
    existing: dict | None,
    partial: dict,
) -> tuple[dict | None, str | None]:
    """
    Merge a partial human_handover_config into the stored config.
    Only keys present in partial are updated.
    """
    is_valid, error_message = validate_human_handover_config(partial)
    if not is_valid:
        return None, error_message

    merged = get_default_human_handover_config()
    if isinstance(existing, dict):
        merged = normalize_human_handover_config(existing)

    for key, value in partial.items():
        if key in ALLOWED_HUMAN_HANDOVER_FIELDS:
            merged[key] = value

    merged = normalize_human_handover_config(merged)

    is_valid, error_message = validate_merged_human_handover_config(merged)
    if not is_valid:
        return None, error_message

    return merged, None
