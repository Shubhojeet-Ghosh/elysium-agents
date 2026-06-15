from typing import Dict, Any, Optional, AsyncGenerator, Union

from openai import AsyncOpenAI

from config.settings import settings
from logging_config import get_logger

logger = get_logger()

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

_deepseek_client: Optional[AsyncOpenAI] = None


def get_deepseek_client() -> AsyncOpenAI:
    """
    Get or create the DeepSeek client (OpenAI-compatible API).
    Uses singleton pattern to reuse the client.
    """
    global _deepseek_client
    if _deepseek_client is None:
        api_key = getattr(settings, "DEEPSEEK_API_KEY", None)
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY is not set in settings. Please add it to your .env file."
            )
        _deepseek_client = AsyncOpenAI(
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
        )
    return _deepseek_client


def serialize_assistant_tool_message(message: Any) -> dict[str, Any]:
    """Convert an OpenAI assistant message (with optional tool_calls) to chat messages format."""
    payload: dict[str, Any] = {
        "role": "assistant",
        "content": message.content,
    }
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]
    return payload


async def deepseek_chat_completion(params: Dict[str, Any]) -> Union[str, AsyncGenerator[str, None]]:
    """
    Chat completion with DeepSeek using the OpenAI-compatible API.

    Args:
        params: Dictionary of parameters. Supported keys:
            - messages (list, required): OpenAI chat messages format
            - model (str): Defaults to "deepseek-v4-flash"
            - temperature (float): Defaults to 0.7
            - stream (bool): Defaults to False

    Returns:
        str (non-stream) or async generator of str (stream)
    """
    model = params.get("model", "deepseek-v4-flash")
    messages = params.get("messages") or []
    temperature = params.get("temperature", 0.7)
    stream = bool(params.get("stream", False))

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("deepseek_chat_completion called without messages; returning empty string")
        return ""

    try:
        client = get_deepseek_client()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=stream,
        )

        if stream:
            async def stream_generator() -> AsyncGenerator[str, None]:
                async for chunk in response:
                    if (
                        chunk.choices
                        and chunk.choices[0].delta
                        and chunk.choices[0].delta.content
                    ):
                        yield chunk.choices[0].delta.content

            logger.debug(
                f"DeepSeek chat completion using model={model}, temperature={temperature}, stream=True"
            )
            return stream_generator()

        content = response.choices[0].message.content if response.choices else ""
        logger.debug(
            f"DeepSeek chat completion using model={model}, temperature={temperature}, stream=False"
        )
        return content or ""
    except Exception as e:
        logger.error(f"Error calling DeepSeek chat completion: {e}")
        raise


async def deepseek_chat_completion_with_tools(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Non-streaming chat completion with OpenAI-style tool definitions.

    Returns:
        {
            "content": str | None,
            "tool_calls": list[dict] | None,
            "assistant_message": dict | None,
        }
    """
    model = params.get("model", "deepseek-v4-pro")
    messages = params.get("messages") or []
    tools = params.get("tools") or []
    temperature = params.get("temperature", 0.3)

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("deepseek_chat_completion_with_tools called without messages")
        return {"content": None, "tool_calls": None, "assistant_message": None}

    try:
        client = get_deepseek_client()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )

        message = response.choices[0].message if response.choices else None
        if not message:
            return {"content": None, "tool_calls": None, "assistant_message": None}

        tool_calls_payload = None
        if message.tool_calls:
            tool_calls_payload = [
                {
                    "id": tool_call.id,
                    "type": tool_call.type,
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in message.tool_calls
            ]

        assistant_message = serialize_assistant_tool_message(message)
        logger.debug(
            f"DeepSeek tool completion model={model}, tool_calls={len(tool_calls_payload or [])}"
        )
        return {
            "content": message.content,
            "tool_calls": tool_calls_payload,
            "assistant_message": assistant_message,
        }
    except Exception as e:
        logger.error(f"Error calling DeepSeek tool completion: {e}", exc_info=True)
        raise
