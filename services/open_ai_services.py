from typing import List, Optional, Dict, Any, AsyncGenerator, Union, Type, TypeVar
from openai import AsyncOpenAI
from pydantic import BaseModel
from logging_config import get_logger
from config.settings import settings

T = TypeVar('T', bound=BaseModel)

logger = get_logger()

# Initialize OpenAI client
_openai_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    """
    Get or create the OpenAI client instance.
    Uses singleton pattern to reuse the client.
    
    Returns:
        AsyncOpenAI: The OpenAI client instance
    """
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


async def get_embeddings(
    texts: List[str],
    model: str = "text-embedding-3-small",
    dimensions: int = 1536
) -> List[List[float]]:
    """
    Get embeddings for a list of texts using OpenAI's embedding API.
    
    Args:
        texts: List of text strings to get embeddings for
        model: The embedding model to use (default: "text-embedding-3-small")
        dimensions: The dimension of the embedding vector (default: 1536)
        
    Returns:
        List[List[float]]: List of embedding vectors, one for each input text
        
    Raises:
        Exception: If the API call fails
    """
    if not texts:
        logger.warning("No texts provided for embedding generation")
        return []
    
    try:
        client = get_openai_client()
        
        # Call OpenAI embeddings API
        response = await client.embeddings.create(
            model=model,
            input=texts,
            dimensions=dimensions
        )
        
        # Extract embeddings from response
        embeddings = [item.embedding for item in response.data]
        
        logger.debug(f"Generated {len(embeddings)} embeddings using model {model} with dimension {dimensions}")
        return embeddings
        
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        raise


async def openai_chat_completion_non_reasoning(params: Dict[str, Any]) -> Union[str, AsyncGenerator[str, None]]:
    """
    General chat completion (non-reasoning) with configurable temperature.

    Args:
        params: Dictionary of parameters. Supported keys:
            - messages (list, required): OpenAI chat messages format
            - model (str): Defaults to "gpt-4o-mini"
            - temperature (float): Defaults to 0.7
            - max_completion_tokens (int): Defaults to 500 (use this instead of max_tokens)
            - top_p (float): Defaults to 1.0
            - response_format (dict | None): OpenAI response_format

    Returns:
        str (non-stream) or async generator of str (stream)
    """
    model = params.get("model", "gpt-4o-mini")
    messages = params.get("messages") or []
    temperature = params.get("temperature", 0.7)
    stream = bool(params.get("stream", False))

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("chat_completion called without messages; returning empty string")
        return ""

    try:
        client = get_openai_client()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=stream,
        )

        if stream:
            async def stream_generator() -> AsyncGenerator[str, None]:
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

            logger.debug(f"Chat completion using model={model}, temperature={temperature}, stream=True")
            return stream_generator()

        content = response.choices[0].message.content if response.choices else ""
        logger.debug(f"Chat completion using model={model}, temperature={temperature}, stream=False")
        return content or ""
    except Exception as e:
        logger.error(f"Error calling chat completion: {e}")
        raise


async def openai_chat_completion_reasoning(params: Dict[str, Any]) -> Union[str, AsyncGenerator[str, None]]:
    """
    Reasoning-oriented completion without temperature (deterministic by default).

    Args:
        params: Dictionary of parameters. Supported keys:
            - messages (list, required): OpenAI chat messages format
            - model (str): Defaults to "gpt-4o-mini"
            - max_completion_tokens (int): Defaults to 500 (use this instead of max_tokens)
            - top_p (float): Defaults to 1.0
            - response_format (dict | None): OpenAI response_format

    Returns:
        str (non-stream) or async generator of str (stream)
    """
    model = params.get("model", "gpt-4o-mini")
    messages = params.get("messages") or []
    stream = bool(params.get("stream", False))

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("reasoning_completion called without messages; returning empty string")
        return ""

    try:
        client = get_openai_client()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=stream,
        )

        if stream:
            async def stream_generator() -> AsyncGenerator[str, None]:
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

            logger.debug(f"Reasoning completion using model={model}, stream=True")
            return stream_generator()

        content = response.choices[0].message.content if response.choices else ""
        logger.debug(f"Reasoning completion using model={model}, stream=False")
        return content or ""
    except Exception as e:
        logger.error(f"Error calling reasoning completion: {e}")
        raise


async def openai_structured_output(
    model: str,
    messages: List[Dict[str, str]],
    response_format: Type[T]
) -> Dict[str, Any]:
    """
    Get structured output from OpenAI using Pydantic BaseModel for parsing.
    
    Args:
        model: The OpenAI model to use (e.g., "gpt-4o-2024-08-06")
        messages: List of chat messages in OpenAI format
        response_format: A Pydantic BaseModel class that defines the expected structure
        
    Returns:
        Dict[str, Any]: The parsed structured output as a dictionary (JSON-serializable)
        
    Raises:
        Exception: If the API call fails or parsing fails
        
    Example:
        ```python
        from pydantic import BaseModel
        
        class ResearchPaperExtraction(BaseModel):
            title: str
            authors: list[str]
            abstract: str
            keywords: list[str]
        
        result = await openai_structured_output(
            model="gpt-4o-2024-08-06",
            messages=[
                {"role": "system", "content": "Extract research paper data."},
                {"role": "user", "content": "..."}
            ],
            response_format=ResearchPaperExtraction
        )
        ```
    """
    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("structured_output called without messages")
        raise ValueError("Messages list cannot be empty")
    
    if not issubclass(response_format, BaseModel):
        logger.error("response_format must be a Pydantic BaseModel class")
        raise ValueError("response_format must be a Pydantic BaseModel class")
    
    try:
        client = get_openai_client()
        response = await client.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_format,
        )
        
        if not response.choices:
            logger.error("No choices returned from OpenAI API")
            raise ValueError("No choices returned from OpenAI API")
        
        parsed = response.choices[0].message.parsed
        if parsed is None:
            logger.error("Failed to parse structured output")
            raise ValueError("Failed to parse structured output")
        
        # Convert Pydantic model to dict (JSON-serializable)
        result = parsed.model_dump()
        logger.debug(f"Structured output parsed successfully using model={model}")
        return result
        
    except Exception as e:
        logger.error(f"Error calling structured output parsing: {e}")
        raise


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


def chat_messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Chat Completions messages to Responses API input items."""
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role in ("user", "system", "developer"):
            items.append({"role": role, "content": message.get("content") or ""})
            continue

        if role == "assistant":
            content = message.get("content")
            if content:
                items.append({"role": "assistant", "content": content})
            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.get("id"),
                        "name": function.get("name"),
                        "arguments": function.get("arguments") or "{}",
                    }
                )
            continue

        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id"),
                    "output": message.get("content") or "",
                }
            )

    return items


def convert_tools_to_responses_format(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Chat Completions tool definitions to Responses API tool definitions."""
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        function = tool.get("function") or {}
        converted.append(
            {
                "type": "function",
                "name": function.get("name"),
                "description": function.get("description") or "",
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted


def _extract_responses_message_text(item: Any) -> str | None:
    content = getattr(item, "content", None)
    if not content:
        return None

    text_parts: list[str] = []
    for part in content:
        part_type = getattr(part, "type", None)
        if part_type == "output_text":
            text = getattr(part, "text", None)
            if text:
                text_parts.append(text)
    return "".join(text_parts) if text_parts else None


def parse_responses_tool_output(response: Any) -> dict[str, Any]:
    """Normalize Responses API output into the shared tool-calling result shape."""
    tool_calls_payload: list[dict[str, Any]] = []
    content_parts: list[str] = []

    for item in response.output or []:
        item_type = getattr(item, "type", None)
        if item_type == "function_call":
            tool_calls_payload.append(
                {
                    "id": item.call_id,
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": item.arguments,
                    },
                }
            )
            continue

        if item_type == "message":
            message_text = _extract_responses_message_text(item)
            if message_text:
                content_parts.append(message_text)

    content = "".join(content_parts) if content_parts else None
    assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls_payload:
        assistant_message["tool_calls"] = tool_calls_payload

    return {
        "content": content,
        "tool_calls": tool_calls_payload or None,
        "assistant_message": assistant_message,
    }


async def openai_chat_completion_with_tools(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Non-streaming Chat Completions call with OpenAI-style tool definitions.

    Reasoning models must use ``reasoning_effort="none"`` for function tools on
    Chat Completions (OpenAI rejects default reasoning effort with tools).
    """
    model = params.get("model", "gpt-4o-mini")
    messages = params.get("messages") or []
    tools = params.get("tools") or []
    temperature = params.get("temperature", 0.3)

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("openai_chat_completion_with_tools called without messages")
        return {"content": None, "tool_calls": None, "assistant_message": None}

    try:
        from config.llm_models_config import get_model_config

        client = get_openai_client()
        model_config = get_model_config(model)
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
        }
        if model_config.get("mode") == "non-reasoning":
            request_kwargs["temperature"] = temperature
        else:
            # GPT-5.6 / GPT-6 Sol/Luna etc.: tools on Chat Completions require none.
            request_kwargs["reasoning_effort"] = "none"

        response = await client.chat.completions.create(**request_kwargs)
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
            f"OpenAI Chat Completions tool call model={model}, "
            f"tool_calls={len(tool_calls_payload or [])}"
        )
        return {
            "content": message.content,
            "tool_calls": tool_calls_payload,
            "assistant_message": assistant_message,
        }
    except Exception as e:
        logger.error(f"Error calling OpenAI Chat Completions tool completion: {e}", exc_info=True)
        raise


async def openai_responses_completion_with_tools(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Non-streaming Responses API call with tool definitions.

    Required for ``gpt-6-astra`` tool calling per OpenAI docs.
    """
    model = params.get("model", "gpt-6-astra")
    messages = params.get("messages") or []
    tools = params.get("tools") or []

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("openai_responses_completion_with_tools called without messages")
        return {"content": None, "tool_calls": None, "assistant_message": None}

    try:
        client = get_openai_client()
        response = await client.responses.create(
            model=model,
            tools=convert_tools_to_responses_format(tools),
            input=chat_messages_to_responses_input(messages),
        )
        parsed = parse_responses_tool_output(response)
        logger.debug(
            f"OpenAI Responses tool call model={model}, "
            f"tool_calls={len(parsed.get('tool_calls') or [])}"
        )
        return parsed
    except Exception as e:
        logger.error(f"Error calling OpenAI Responses tool completion: {e}", exc_info=True)
        raise