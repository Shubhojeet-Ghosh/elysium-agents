"""
Lead collection settings for atlas agents.
Extend ALLOWED_LEAD_COLLECTION_FIELDS and FIELD_VALIDATORS when adding new keys.
"""

ENABLE_LEAD_CAPTURING_KEY = "enable_lead_capturing"

DEFAULT_LEAD_COLLECTION_CONFIG: dict = {
    ENABLE_LEAD_CAPTURING_KEY: False,
}

ALLOWED_LEAD_COLLECTION_FIELDS = frozenset(DEFAULT_LEAD_COLLECTION_CONFIG.keys())


def get_default_lead_collection_config() -> dict:
    return dict(DEFAULT_LEAD_COLLECTION_CONFIG)


def _validate_enable_lead_capturing(value) -> tuple[bool, str | None]:
    if not isinstance(value, bool):
        return False, f"{ENABLE_LEAD_CAPTURING_KEY} must be a boolean."
    return True, None


FIELD_VALIDATORS = {
    ENABLE_LEAD_CAPTURING_KEY: _validate_enable_lead_capturing,
}


def validate_lead_collection_config(config) -> tuple[bool, str | None]:
    """
    Validate a lead_collection_config object (full or partial).

    Only keys present in config are validated; use for partial updates.
    """
    if config is None:
        return True, None

    if not isinstance(config, dict):
        return False, "lead_collection_config must be an object."

    unknown = set(config.keys()) - ALLOWED_LEAD_COLLECTION_FIELDS
    if unknown:
        allowed = ", ".join(sorted(ALLOWED_LEAD_COLLECTION_FIELDS))
        invalid = ", ".join(sorted(unknown))
        return False, (
            f"Invalid lead_collection_config field(s): {invalid}. "
            f"Allowed fields: {allowed}."
        )

    for key, value in config.items():
        validator = FIELD_VALIDATORS.get(key)
        if validator is None:
            continue
        is_valid, error_message = validator(value)
        if not is_valid:
            return False, error_message

    return True, None


def build_lead_collection_config_for_create(override: dict | None = None) -> tuple[dict, str | None]:
    """
    Build lead_collection_config for new agents, starting from defaults.

    Returns:
        (config, error_message)
    """
    config = get_default_lead_collection_config()
    if override is None:
        return config, None

    is_valid, error_message = validate_lead_collection_config(override)
    if not is_valid:
        return config, error_message

    config.update(override)
    return config, None


def merge_lead_collection_config(
    existing: dict | None,
    partial: dict,
) -> tuple[dict | None, str | None]:
    """
    Merge a partial lead_collection_config into the stored config.
    Only keys present in partial are updated.
    """
    is_valid, error_message = validate_lead_collection_config(partial)
    if not is_valid:
        return None, error_message

    merged = get_default_lead_collection_config()
    if isinstance(existing, dict):
        for key in ALLOWED_LEAD_COLLECTION_FIELDS:
            if key in existing:
                merged[key] = existing[key]

    for key, value in partial.items():
        if key in ALLOWED_LEAD_COLLECTION_FIELDS:
            merged[key] = value

    return merged, None
