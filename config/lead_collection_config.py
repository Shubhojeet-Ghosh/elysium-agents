"""
Lead collection settings for atlas agents.
Extend ALLOWED_LEAD_COLLECTION_FIELDS and FIELD_VALIDATORS when adding new keys.
"""

ENABLE_LEAD_CAPTURING_KEY = "enable_lead_capturing"
COLLECTION_TRIGGER_PROMPT_KEY = "collection_trigger_prompt"
MIN_MESSAGES_BEFORE_ASK_KEY = "min_messages_before_ask"
FIELDS_KEY = "fields"

ALLOWED_LEAD_FIELD_KEYS = frozenset({
    "email",
    "name",
    "phone",
    "company",
    "interest",
})

LEAD_FIELD_CATALOG: list[dict[str, str]] = [
    {
        "key": "email",
        "label": "Email",
        "description": "Visitor email address.",
    },
    {
        "key": "name",
        "label": "Name",
        "description": "Visitor full name.",
    },
    {
        "key": "phone",
        "label": "Phone",
        "description": "Visitor phone number.",
    },
    {
        "key": "company",
        "label": "Company",
        "description": "Visitor company or organization.",
    },
    {
        "key": "interest",
        "label": "Interest",
        "description": "What the visitor is interested in; can be auto-summarized from chat.",
    },
]

COLLECTION_TRIGGER_PROMPT_MIN_LENGTH = 10
COLLECTION_TRIGGER_PROMPT_MAX_LENGTH = 500
DEFAULT_MIN_MESSAGES_BEFORE_ASK = 2
MIN_MESSAGES_BEFORE_ASK_MIN = 1
MIN_MESSAGES_BEFORE_ASK_MAX = 50
MAX_LEAD_COLLECTION_FIELDS = 10

DEFAULT_LEAD_COLLECTION_CONFIG: dict = {
    ENABLE_LEAD_CAPTURING_KEY: False,
    COLLECTION_TRIGGER_PROMPT_KEY: "",
    MIN_MESSAGES_BEFORE_ASK_KEY: DEFAULT_MIN_MESSAGES_BEFORE_ASK,
    FIELDS_KEY: [],
}

ALLOWED_LEAD_COLLECTION_FIELDS = frozenset(DEFAULT_LEAD_COLLECTION_CONFIG.keys())


def get_default_lead_collection_config() -> dict:
    return dict(DEFAULT_LEAD_COLLECTION_CONFIG)


def get_lead_field_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in LEAD_FIELD_CATALOG]


def _validate_enable_lead_capturing(value) -> tuple[bool, str | None]:
    if not isinstance(value, bool):
        return False, f"{ENABLE_LEAD_CAPTURING_KEY} must be a boolean."
    return True, None


def _validate_collection_trigger_prompt(value, *, enabled: bool) -> tuple[bool, str | None]:
    if value is None:
        if enabled:
            return False, f"{COLLECTION_TRIGGER_PROMPT_KEY} is required when lead capturing is enabled."
        return True, None

    if not isinstance(value, str):
        return False, f"{COLLECTION_TRIGGER_PROMPT_KEY} must be a string."

    normalized = value.strip()
    if not enabled:
        return True, None

    if len(normalized) < COLLECTION_TRIGGER_PROMPT_MIN_LENGTH:
        return (
            False,
            f"{COLLECTION_TRIGGER_PROMPT_KEY} must be at least "
            f"{COLLECTION_TRIGGER_PROMPT_MIN_LENGTH} characters when lead capturing is enabled.",
        )

    if len(normalized) > COLLECTION_TRIGGER_PROMPT_MAX_LENGTH:
        return (
            False,
            f"{COLLECTION_TRIGGER_PROMPT_KEY} must be at most "
            f"{COLLECTION_TRIGGER_PROMPT_MAX_LENGTH} characters.",
        )

    return True, None


def _validate_min_messages_before_ask(value) -> tuple[bool, str | None]:
    if value is None:
        return True, None

    if not isinstance(value, int) or isinstance(value, bool):
        return False, f"{MIN_MESSAGES_BEFORE_ASK_KEY} must be an integer."

    if value < MIN_MESSAGES_BEFORE_ASK_MIN or value > MIN_MESSAGES_BEFORE_ASK_MAX:
        return (
            False,
            f"{MIN_MESSAGES_BEFORE_ASK_KEY} must be between "
            f"{MIN_MESSAGES_BEFORE_ASK_MIN} and {MIN_MESSAGES_BEFORE_ASK_MAX}.",
        )

    return True, None


def _validate_fields(value, *, enabled: bool) -> tuple[bool, str | None]:
    if value is None:
        if enabled:
            return False, f"{FIELDS_KEY} must contain at least one field when lead capturing is enabled."
        return True, None

    if not isinstance(value, list):
        return False, f"{FIELDS_KEY} must be an array."

    if enabled and len(value) < 1:
        return False, f"{FIELDS_KEY} must contain at least one field when lead capturing is enabled."

    if len(value) > MAX_LEAD_COLLECTION_FIELDS:
        return (
            False,
            f"{FIELDS_KEY} must contain at most {MAX_LEAD_COLLECTION_FIELDS} items.",
        )

    seen_orders: set[int] = set()
    seen_keys: set[str] = set()

    for index, item in enumerate(value):
        if not isinstance(item, dict):
            return False, f"{FIELDS_KEY}[{index}] must be an object."

        field_key = item.get("key")
        if not isinstance(field_key, str) or field_key not in ALLOWED_LEAD_FIELD_KEYS:
            allowed = ", ".join(sorted(ALLOWED_LEAD_FIELD_KEYS))
            return False, f"{FIELDS_KEY}[{index}].key must be one of: {allowed}."

        if field_key in seen_keys:
            return False, f"{FIELDS_KEY} contains duplicate key '{field_key}'."

        required = item.get("required")
        if not isinstance(required, bool):
            return False, f"{FIELDS_KEY}[{index}].required must be a boolean."

        order = item.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order < 1:
            return False, f"{FIELDS_KEY}[{index}].order must be an integer >= 1."

        if order in seen_orders:
            return False, f"{FIELDS_KEY} contains duplicate order value {order}."

        seen_orders.add(order)
        seen_keys.add(field_key)

    return True, None


def _normalize_collection_trigger_prompt(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _normalize_fields(value) -> list[dict]:
    if not isinstance(value, list):
        return []

    normalized: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        field_key = item.get("key")
        if field_key not in ALLOWED_LEAD_FIELD_KEYS:
            continue
        normalized.append(
            {
                "key": field_key,
                "required": bool(item.get("required")),
                "order": int(item["order"]),
            }
        )

    return sorted(normalized, key=lambda field: field["order"])


def normalize_lead_collection_config(config: dict) -> dict:
    """Return a normalized copy of a full lead_collection_config object."""
    normalized = get_default_lead_collection_config()
    if not isinstance(config, dict):
        return normalized

    if ENABLE_LEAD_CAPTURING_KEY in config:
        normalized[ENABLE_LEAD_CAPTURING_KEY] = bool(config[ENABLE_LEAD_CAPTURING_KEY])

    if COLLECTION_TRIGGER_PROMPT_KEY in config:
        normalized[COLLECTION_TRIGGER_PROMPT_KEY] = _normalize_collection_trigger_prompt(
            config[COLLECTION_TRIGGER_PROMPT_KEY]
        )

    if MIN_MESSAGES_BEFORE_ASK_KEY in config and config[MIN_MESSAGES_BEFORE_ASK_KEY] is not None:
        normalized[MIN_MESSAGES_BEFORE_ASK_KEY] = int(config[MIN_MESSAGES_BEFORE_ASK_KEY])

    if FIELDS_KEY in config and config[FIELDS_KEY] is not None:
        normalized[FIELDS_KEY] = _normalize_fields(config[FIELDS_KEY])

    return normalized


def validate_lead_collection_config(config, *, validate_enabled_requirements: bool = False) -> tuple[bool, str | None]:
    """
    Validate a lead_collection_config object (full or partial).

    Only keys present in config are validated; use for partial updates.
    When validate_enabled_requirements is True, also enforce cross-field rules
    for the merged config (e.g. prompt required when enabled).
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

    field_validators = {
        ENABLE_LEAD_CAPTURING_KEY: _validate_enable_lead_capturing,
        MIN_MESSAGES_BEFORE_ASK_KEY: _validate_min_messages_before_ask,
    }

    for key, value in config.items():
        validator = field_validators.get(key)
        if validator is None:
            continue
        is_valid, error_message = validator(value)
        if not is_valid:
            return False, error_message

    enabled = bool(config.get(ENABLE_LEAD_CAPTURING_KEY)) if ENABLE_LEAD_CAPTURING_KEY in config else False

    if COLLECTION_TRIGGER_PROMPT_KEY in config:
        is_valid, error_message = _validate_collection_trigger_prompt(
            config[COLLECTION_TRIGGER_PROMPT_KEY],
            enabled=enabled if validate_enabled_requirements else False,
        )
        if not is_valid:
            return False, error_message

    if FIELDS_KEY in config:
        is_valid, error_message = _validate_fields(
            config[FIELDS_KEY],
            enabled=enabled if validate_enabled_requirements else False,
        )
        if not is_valid:
            return False, error_message

    return True, None


def validate_merged_lead_collection_config(config: dict) -> tuple[bool, str | None]:
    """Validate a full merged lead_collection_config, including enabled cross-field rules."""
    if not isinstance(config, dict):
        return False, "lead_collection_config must be an object."

    is_valid, error_message = validate_lead_collection_config(config)
    if not is_valid:
        return False, error_message

    normalized = normalize_lead_collection_config(config)
    enabled = normalized[ENABLE_LEAD_CAPTURING_KEY]

    is_valid, error_message = _validate_collection_trigger_prompt(
        normalized[COLLECTION_TRIGGER_PROMPT_KEY],
        enabled=enabled,
    )
    if not is_valid:
        return False, error_message

    is_valid, error_message = _validate_fields(normalized[FIELDS_KEY], enabled=enabled)
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
    config = normalize_lead_collection_config(config)

    is_valid, error_message = validate_merged_lead_collection_config(config)
    if not is_valid:
        return get_default_lead_collection_config(), error_message

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
        merged = normalize_lead_collection_config(existing)

    for key, value in partial.items():
        if key in ALLOWED_LEAD_COLLECTION_FIELDS:
            merged[key] = value

    merged = normalize_lead_collection_config(merged)

    is_valid, error_message = validate_merged_lead_collection_config(merged)
    if not is_valid:
        return None, error_message

    return merged, None
