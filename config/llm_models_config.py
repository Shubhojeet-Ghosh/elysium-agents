"""
Central registry for LLM models → metadata and handler selection.
Scalable: add entries to MODEL_REGISTRY to support new models/functions.
"""
from typing import Callable, Dict, Any, Tuple

from services.open_ai_services import (
    openai_chat_completion_non_reasoning,
    openai_chat_completion_reasoning,
)
from services.groq_services import groq_chat_completions
from services.claude_services import claude_chat_completion_non_reasoning

# Default model if none provided or lookup fails
DEFAULT_MODEL = "gpt-4o-mini"

# Registry keyed by model name. Each entry can include:
# - family: logical family/grouping of the model
# - mode: "chat" | "reasoning" | other future modes
# - handler: callable that will be invoked for this model
MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # Non-reasoning (temperature-enabled) chat
    "gpt-4o-mini": {
        "family": "openai-gpt-4o",
        "mode": "non-reasoning",
        "handler": openai_chat_completion_non_reasoning,
    },
    "gpt-4.1-mini": {
        "family": "gpt-4.1-mini-2025-04-14",
        "mode": "non-reasoning",
        "handler": openai_chat_completion_non_reasoning,
    },
    # Reasoning-oriented (no temperature)
    "gpt-5-nano-2025-08-07": {
        "family": "openai-gpt-5-nano",
        "mode": "reasoning",
        "handler": openai_chat_completion_reasoning,
    },
    # Groq chat
    "openai/gpt-oss-120b": {
        "family": "groq",
        "mode": "reasoning",
        "handler": groq_chat_completions,
    },
    "openai/gpt-oss-20b": {
        "family": "groq",
        "mode": "reasoning",
        "handler": groq_chat_completions,
    },
     "claude-3-7-sonnet-latest": {
        "family": "claude",
        "mode": "non-reasoning",
        "handler": claude_chat_completion_non_reasoning,
    },
     "claude-sonnet-4-0": {
        "family": "claude",
        "mode": "non-reasoning",
        "handler": claude_chat_completion_non_reasoning,
    },
    "claude-sonnet-4-5": {
        "family": "claude",
        "mode": "non-reasoning",
        "handler": claude_chat_completion_non_reasoning,
    },
     "claude-haiku-4-5": {
        "family": "claude",
        "mode": "non-reasoning",
        "handler": claude_chat_completion_non_reasoning,
    },
}


def get_model_config(model_name: str) -> Dict[str, Any]:
    """
    Return config for a model; fallback to default model if not found.
    """
    if model_name in MODEL_REGISTRY:
        return MODEL_REGISTRY[model_name]
    return MODEL_REGISTRY[DEFAULT_MODEL]


def resolve_model_handler(model_name: str) -> Tuple[Callable[..., Any], Dict[str, Any]]:
    """
    Return (handler, config) for the given model, falling back to default.
    """
    config = get_model_config(model_name)
    handler = config["handler"]
    return handler, config

