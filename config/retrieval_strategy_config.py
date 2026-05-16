"""
Allowed retrieval strategies for atlas agents.
- simple: standard single-pass RAG
- orchestrated: multi-query / advanced orchestrated retrieval
"""

RETRIEVAL_STRATEGY_SIMPLE = "simple"
RETRIEVAL_STRATEGY_ORCHESTRATED = "orchestrated"

ALLOWED_RETRIEVAL_STRATEGIES = frozenset({
    RETRIEVAL_STRATEGY_SIMPLE,
    RETRIEVAL_STRATEGY_ORCHESTRATED,
})

DEFAULT_RETRIEVAL_STRATEGY = RETRIEVAL_STRATEGY_SIMPLE


def validate_retrieval_strategy(value) -> tuple[bool, str | None, str | None]:
    """
    Validate a retrieval_strategy value.

    Returns:
        (is_valid, normalized_value, error_message)
        normalized_value is set only when is_valid and value is not None.
    """
    if value is None:
        return True, None, None

    if not isinstance(value, str):
        return False, None, "retrieval_strategy must be a string."

    normalized = value.strip().lower()
    if normalized not in ALLOWED_RETRIEVAL_STRATEGIES:
        allowed = ", ".join(sorted(ALLOWED_RETRIEVAL_STRATEGIES))
        return False, None, f"Invalid retrieval_strategy '{value}'. Allowed values: {allowed}."

    return True, normalized, None


def normalize_retrieval_strategy_in_request(request_data: dict) -> str | None:
    """
    If retrieval_strategy is present in request_data, validate and normalize in place.

    Returns:
        Error message when invalid, otherwise None.
    """
    if "retrieval_strategy" not in request_data:
        return None

    is_valid, normalized, error_message = validate_retrieval_strategy(
        request_data.get("retrieval_strategy")
    )
    if not is_valid:
        return error_message

    if normalized is not None:
        request_data["retrieval_strategy"] = normalized

    return None
