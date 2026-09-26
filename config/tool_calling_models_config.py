"""
Registry of models allowed for Atlas tool/plugin orchestration.

Default remains DeepSeek for legacy agents missing ``tool_calling_model``.
OpenAI response-generation models are supported via Chat Completions tools,
except ``gpt-6-astra`` which requires the Responses API per OpenAI docs.
Claude models use the Messages API tool_use / tool_result flow.
"""

from config.llm_models_config import MODEL_REGISTRY, get_model_config

DEFAULT_TOOL_CALLING_MODEL = "deepseek-v4-pro"

_DEEPSEEK_TOOL_CALLING_MODELS = frozenset({"deepseek-v4-pro", "deepseek-v4-flash"})

_OPENAI_RESPONSES_TOOL_CALLING_MODELS = frozenset({"gpt-6-astra"})

_OPENAI_CHAT_TOOL_CALLING_MODELS = frozenset(
    model_id
    for model_id, config in MODEL_REGISTRY.items()
    if str(config.get("family", "")).startswith("openai-gpt")
    and model_id not in _OPENAI_RESPONSES_TOOL_CALLING_MODELS
)

_CLAUDE_TOOL_CALLING_MODELS = frozenset(
    model_id
    for model_id, config in MODEL_REGISTRY.items()
    if config.get("family") == "claude"
)

SUPPORTED_TOOL_CALLING_MODELS = frozenset(
    _DEEPSEEK_TOOL_CALLING_MODELS
    | _OPENAI_CHAT_TOOL_CALLING_MODELS
    | _OPENAI_RESPONSES_TOOL_CALLING_MODELS
    | _CLAUDE_TOOL_CALLING_MODELS
)


def get_tool_calling_api(model_name: str) -> str:
    """Return orchestration API backend: deepseek | openai-chat | openai-responses | claude."""
    if model_name in _DEEPSEEK_TOOL_CALLING_MODELS:
        return "deepseek"
    if model_name in _OPENAI_RESPONSES_TOOL_CALLING_MODELS:
        return "openai-responses"
    if model_name in _OPENAI_CHAT_TOOL_CALLING_MODELS:
        return "openai-chat"
    if model_name in _CLAUDE_TOOL_CALLING_MODELS:
        return "claude"
    return "unknown"


def get_selectable_tool_calling_models() -> list[dict[str, str | bool]]:
    """
    Models to expose in frontend pickers.

    Deprecated registry entries remain API-valid but are hidden from new selections.
    """
    models: list[dict[str, str | bool]] = []
    for model_id in sorted(SUPPORTED_TOOL_CALLING_MODELS):
        config = MODEL_REGISTRY.get(model_id, {})
        models.append(
            {
                "model_id": model_id,
                "provider": get_tool_calling_api(model_id).split("-", 1)[0],
                "deprecated": bool(config.get("deprecated")),
                "default": model_id == DEFAULT_TOOL_CALLING_MODEL,
            }
        )
    return models


def get_tool_calling_model_config(model_name: str) -> dict:
    """Return orchestration metadata for a tool-calling model."""
    if model_name not in SUPPORTED_TOOL_CALLING_MODELS:
        return {
            "model": DEFAULT_TOOL_CALLING_MODEL,
            "api": get_tool_calling_api(DEFAULT_TOOL_CALLING_MODEL),
            "mode": get_model_config(DEFAULT_TOOL_CALLING_MODEL).get("mode", "non-reasoning"),
        }

    return {
        "model": model_name,
        "api": get_tool_calling_api(model_name),
        "mode": get_model_config(model_name).get("mode", "non-reasoning"),
    }


def validate_tool_calling_model(value) -> tuple[bool, str | None, str | None]:
    """
    Validate a tool_calling_model value.

    Returns:
        (is_valid, normalized_value, error_message)
    """
    if value is None:
        return True, None, None

    if not isinstance(value, str):
        return False, None, "tool_calling_model must be a string."

    normalized = value.strip()
    if not normalized:
        return False, None, "tool_calling_model must be a non-empty string."

    if normalized not in SUPPORTED_TOOL_CALLING_MODELS:
        allowed = ", ".join(sorted(SUPPORTED_TOOL_CALLING_MODELS))
        return (
            False,
            None,
            f"Invalid tool_calling_model '{value}'. Allowed values: {allowed}.",
        )

    return True, normalized, None
