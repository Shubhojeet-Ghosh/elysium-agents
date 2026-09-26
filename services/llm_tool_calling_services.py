"""Dispatch tool/plugin orchestration to the configured model provider."""

from typing import Any

from config.tool_calling_models_config import (
    DEFAULT_TOOL_CALLING_MODEL,
    get_tool_calling_model_config,
)
from logging_config import get_logger
from services.claude_services import claude_chat_completion_with_tools
from services.deepseek_services import deepseek_chat_completion_with_tools
from services.open_ai_services import (
    openai_chat_completion_with_tools,
    openai_responses_completion_with_tools,
)

logger = get_logger()


async def chat_completion_with_tools(params: dict[str, Any]) -> dict[str, Any]:
    """
    Run a non-streaming tool-calling completion for Atlas orchestration.

    Returns:
        {
            "content": str | None,
            "tool_calls": list[dict] | None,
            "assistant_message": dict | None,
        }
    """
    model = params.get("model") or DEFAULT_TOOL_CALLING_MODEL
    model_config = get_tool_calling_model_config(model)
    api = model_config["api"]
    request_params = {**params, "model": model}

    if api == "deepseek":
        return await deepseek_chat_completion_with_tools(request_params)
    if api == "openai-chat":
        return await openai_chat_completion_with_tools(request_params)
    if api == "openai-responses":
        return await openai_responses_completion_with_tools(request_params)
    if api == "claude":
        return await claude_chat_completion_with_tools(request_params)

    logger.error(f"Unsupported tool calling API '{api}' for model={model}")
    raise ValueError(f"Unsupported tool calling model: {model}")
