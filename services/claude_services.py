from typing import List, Dict, Any, Optional, Type, Literal, Union, AsyncGenerator
import json
from enum import Enum
from pydantic import create_model, BaseModel, Field
from anthropic import Anthropic, AsyncAnthropic
from logging_config import get_logger
from config.settings import settings

logger = get_logger()

# Sonnet 5 rejects non-default temperature, top_p, and top_k.
# Adaptive thinking is on by default and shares the max_tokens budget with the reply.
CLAUDE_SONNET_5_MODEL = "claude-sonnet-5"
CLAUDE_SONNET_5_DEFAULT_MAX_TOKENS = 4096

# Initialize Anthropic client
_claude_client: Optional[Anthropic] = None
_claude_async_client: Optional[AsyncAnthropic] = None


def get_claude_client() -> Anthropic:
    """
    Get or create the Anthropic Claude client instance.
    Uses singleton pattern to reuse the client.
    
    Returns:
        Anthropic: The Anthropic client instance
    """
    global _claude_client
    if _claude_client is None:
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in settings. Please add it to your .env file.")
        _claude_client = Anthropic(api_key=api_key)
    return _claude_client


def get_claude_async_client() -> AsyncAnthropic:
    """
    Get or create the async Anthropic Claude client instance.
    Uses singleton pattern to reuse the client.
    
    Returns:
        AsyncAnthropic: The async Anthropic client instance
    """
    global _claude_async_client
    if _claude_async_client is None:
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in settings. Please add it to your .env file.")
        _claude_async_client = AsyncAnthropic(api_key=api_key)
    return _claude_async_client


def _create_dynamic_pydantic_model(fields: List[Dict[str, Any]]) -> Type[BaseModel]:
    """
    Dynamically create a Pydantic model from a list of field definitions.
    
    Args:
        fields: List of dictionaries with 'key_name', 'type', and optional 'enum' keys
                Example: [
                    {"key_name": "email", "type": "str"}, 
                    {"key_name": "demo_requested", "type": "bool"},
                    {"key_name": "status", "type": "str", "enum": ["active", "inactive", "pending"]}
                ]
    
    Returns:
        Type[BaseModel]: A dynamically created Pydantic model class
    """
    field_definitions = {}
    
    for field in fields:
        key_name = field.get("key_name")
        field_type = field.get("type", "str")
        enum_values = field.get("enum")
        
        if not key_name:
            logger.warning(f"Skipping field without key_name: {field}")
            continue
        
        # If enum is provided, create a Literal type
        if enum_values and isinstance(enum_values, list) and len(enum_values) > 0:
            # Create a Literal type with the enum values
            # e.g., Literal["active", "inactive", "pending"]
            # Note: We don't wrap in Optional to avoid "too many conditional branches" error
            # The model must return one of the enum values
            literal_type = Literal[tuple(enum_values)]
            field_definitions[key_name] = (literal_type, ...)  # ... means required field
            logger.debug(f"Created enum field '{key_name}' with values: {enum_values}")
        else:
            # Map type strings to Python types (for non-enum fields)
            type_mapping = {
                "str": str,
                "string": str,
                "bool": bool,
                "boolean": bool,
                "int": int,
                "integer": int,
                "float": float,
                "number": float,
                "list": list,
                "dict": dict,
            }
            
            python_type = type_mapping.get(field_type.lower(), str)
            
            # Make all fields nullable so missing data can be set to None/null
            # Fields are still required in the schema (must be present), but can be null
            field_definitions[key_name] = (Optional[python_type], None)
    
    if not field_definitions:
        raise ValueError("No valid fields provided. At least one field with 'key_name' is required.")
    
    # Create the model dynamically
    DynamicModel = create_model("DynamicOutputModel", **field_definitions)
    return DynamicModel


def get_structured_output(
    fields: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-5",
    max_tokens: int = 4096,
    **kwargs
) -> Dict[str, Any]:
    """
    Get structured JSON output from Claude using dynamic Pydantic model.
    
    Args:
        fields: List of field definitions. Each field should have:
               - key_name (str): The name of the field
               - type (str): The type of the field (str, bool, int, float, list, dict)
               - enum (list, optional): List of allowed values for the field (creates a Literal type)
               - required (bool, optional): Whether the field is required (default: True)
               Example: [
                   {"key_name": "email", "type": "str"},
                   {"key_name": "demo_requested", "type": "bool"},
                   {"key_name": "status", "type": "str", "enum": ["active", "inactive", "pending"]},
                   {"key_name": "age", "type": "int", "required": False}
               ]
        messages: List of message dictionaries in Claude's format.
                 Example: [
                     {
                         "role": "user",
                         "content": "Extract the key information from this email: John Smith (john@example.com) is interested in our Enterprise plan."
                     }
                 ]
        model: Claude model to use (default: "claude-sonnet-4-5")
        max_tokens: Maximum tokens in response (default: 4096, can be overridden)
        **kwargs: Additional parameters to pass to the API call
    
    Returns:
        Dict[str, Any]: Dictionary containing:
            - "data": The structured JSON output matching the schema
            - "usage": Dictionary with token usage:
                - "input_tokens": Number of input tokens used
                - "output_tokens": Number of output tokens used
    
    Raises:
        ValueError: If fields or messages are invalid
        Exception: If the API call fails
    """
    if not fields:
        raise ValueError("fields list cannot be empty")
    
    if not messages:
        raise ValueError("messages list cannot be empty")
    
    try:
        # Create dynamic Pydantic model from fields
        DynamicModel = _create_dynamic_pydantic_model(fields)
        
        # Get Claude client
        client = get_claude_client()
        
        # Prepare API call parameters
        api_params = {
            "model": model,
            "max_tokens": max_tokens,
            "betas": ["structured-outputs-2025-11-13"],
            "messages": messages,
            "output_format": DynamicModel,  # Pass Pydantic model directly to .parse()
        }
        
        # Add any additional kwargs
        api_params.update(kwargs)
        
        # Make API call with structured outputs using .parse()
        response = client.beta.messages.parse(**api_params)
        
        # Get parsed output as dictionary
        # Use model_dump() for Pydantic v2, or dict() for v1
        if hasattr(response.parsed_output, 'model_dump'):
            structured_output = response.parsed_output.model_dump()
        else:
            structured_output = response.parsed_output.dict()
        
        # Ensure all fields are present, setting null for any missing fields
        expected_field_names = [field.get("key_name") for field in fields if field.get("key_name")]
        for field_name in expected_field_names:
            if field_name not in structured_output:
                structured_output[field_name] = None
                logger.debug(f"Field '{field_name}' not found in response, setting to null")
        
        # Extract token usage information
        if hasattr(response, 'usage') and response.usage:
            usage_info = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        else:
            usage_info = {
                "input_tokens": 0,
                "output_tokens": 0,
            }
        
        logger.debug(f"Successfully generated structured output with {len(fields)} fields. Input tokens: {usage_info['input_tokens']}, Output tokens: {usage_info['output_tokens']}")
        
        return {
            "structured_output": structured_output,
            "usage": usage_info
        }
        
    except Exception as e:
        # Check if it's a parsing/validation error from Pydantic
        if "parsed_output" in str(e) or "validation" in str(e).lower():
            logger.error(f"Failed to parse/validate response: {e}")
            raise ValueError(f"Invalid response from Claude: {e}")
        logger.error(f"Error calling Claude structured outputs API: {e}")
        raise


async def claude_chat_completion_non_reasoning(params: Dict[str, Any]) -> Union[str, AsyncGenerator[str, None]]:
    """
    General chat completion (non-reasoning) with configurable temperature.

    Args:
        params: Dictionary of parameters. Supported keys:
            - messages (list, required): Claude chat messages format
            - model (str): Defaults to "claude-sonnet-4-5"
            - temperature (float): Defaults to 0.7
            - max_completion_tokens (int): Defaults to 500 (mapped to max_tokens for Claude)
            - stream (bool): Whether to stream the response (defaults to False)

    Returns:
        str (non-stream) or async generator of str (stream)
    """
    model = params.get("model", "claude-sonnet-4-5")
    messages = params.get("messages") or []
    temperature = params.get("temperature", 0.7)
    is_sonnet_5 = model == CLAUDE_SONNET_5_MODEL
    if "max_completion_tokens" in params:
        max_completion_tokens = params["max_completion_tokens"]
    elif is_sonnet_5:
        max_completion_tokens = CLAUDE_SONNET_5_DEFAULT_MAX_TOKENS
    else:
        max_completion_tokens = 500
    stream = bool(params.get("stream", False))

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("claude_chat_completion_non_reasoning called without messages; returning empty string")
        return ""

    try:
        client = get_claude_async_client()
        
        # Extract system messages and convert to Claude's format
        system_content = ""
        filtered_messages = []
        
        for message in messages:
            if message.get("role") == "system":
                if system_content:
                    system_content += "\n\n"
                system_content += message.get("content", "")
            else:
                filtered_messages.append(message)
        
        # Prepare API call parameters
        api_params = {
            "model": model,
            "messages": filtered_messages,  # Only user/assistant messages
            "max_tokens": max_completion_tokens,  # Claude uses max_tokens instead of max_completion_tokens
            "stream": stream,
        }
        if not is_sonnet_5:
            api_params["temperature"] = temperature
        
        # Add system parameter if we have system content
        if system_content.strip():
            api_params["system"] = system_content.strip()
        
        response = await client.messages.create(**api_params)

        if stream:
            async def stream_generator() -> AsyncGenerator[str, None]:
                async for chunk in response:
                    delta = getattr(chunk, "delta", None)
                    if getattr(delta, "type", None) == "text_delta":
                        text = getattr(delta, "text", None)
                        if text:
                            yield text
                        continue
                    content_block = getattr(chunk, "content_block", None)
                    if getattr(content_block, "type", None) == "text":
                        text = getattr(content_block, "text", None)
                        if text:
                            yield text

            logger.debug(f"Claude chat completion using model={model}, temperature={temperature}, stream=True")
            return stream_generator()

        # Non-streaming response
        content = ""
        if hasattr(response, 'content') and response.content:
            for block in response.content:
                if getattr(block, "type", None) == "text" and getattr(block, "text", None):
                    content += block.text
        
        logger.debug(f"Claude chat completion using model={model}, temperature={temperature}, stream=False")
        return content or ""
        
    except Exception as e:
        logger.error(f"Error calling Claude chat completion: {e}")
        raise


CLAUDE_TOOL_CALLING_DEFAULT_MAX_TOKENS = 2048


def convert_openai_tools_to_claude(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-style tool definitions to Claude Messages API tools."""
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        function = tool.get("function") or {}
        converted.append(
            {
                "name": function.get("name"),
                "description": function.get("description") or "",
                "input_schema": function.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return converted


def _append_claude_tool_result(
    claude_messages: list[dict[str, Any]],
    tool_call_id: str,
    content: str,
) -> None:
    block = {
        "type": "tool_result",
        "tool_use_id": tool_call_id,
        "content": content,
    }
    if (
        claude_messages
        and claude_messages[-1]["role"] == "user"
        and isinstance(claude_messages[-1]["content"], list)
        and claude_messages[-1]["content"]
        and claude_messages[-1]["content"][0].get("type") == "tool_result"
    ):
        claude_messages[-1]["content"].append(block)
        return

    claude_messages.append({"role": "user", "content": [block]})


def chat_messages_to_claude_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert OpenAI-style orchestration messages to Claude Messages API format."""
    system_parts: list[str] = []
    claude_messages: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        if role == "system":
            content = message.get("content")
            if content:
                system_parts.append(str(content))
            continue

        if role == "user":
            claude_messages.append({"role": "user", "content": message.get("content") or ""})
            continue

        if role == "assistant":
            content = message.get("content")
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                blocks: list[dict[str, Any]] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tool_call in tool_calls:
                    function = tool_call.get("function") or {}
                    raw_arguments = function.get("arguments") or "{}"
                    try:
                        parsed_arguments = (
                            json.loads(raw_arguments)
                            if isinstance(raw_arguments, str)
                            else raw_arguments
                        )
                    except json.JSONDecodeError:
                        parsed_arguments = {}
                    if not isinstance(parsed_arguments, dict):
                        parsed_arguments = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tool_call.get("id"),
                            "name": function.get("name"),
                            "input": parsed_arguments,
                        }
                    )
                claude_messages.append({"role": "assistant", "content": blocks})
            else:
                claude_messages.append({"role": "assistant", "content": content or ""})
            continue

        if role == "tool":
            _append_claude_tool_result(
                claude_messages,
                str(message.get("tool_call_id") or ""),
                str(message.get("content") or ""),
            )

    return "\n\n".join(system_parts), claude_messages


def parse_claude_tool_response(response: Any) -> dict[str, Any]:
    """Normalize Claude tool_use output into the shared orchestration result shape."""
    tool_calls_payload: list[dict[str, Any]] = []
    text_parts: list[str] = []

    for block in getattr(response, "content", None) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", None)
            if text:
                text_parts.append(text)
            continue

        if block_type == "tool_use":
            tool_input = getattr(block, "input", None) or {}
            tool_calls_payload.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(tool_input),
                    },
                }
            )

    content = "".join(text_parts) if text_parts else None
    assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls_payload:
        assistant_message["tool_calls"] = tool_calls_payload

    return {
        "content": content,
        "tool_calls": tool_calls_payload or None,
        "assistant_message": assistant_message,
    }


async def claude_chat_completion_with_tools(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Non-streaming Messages API call with Claude tool definitions.

    Accepts OpenAI-style tools/messages used by Atlas orchestration and returns the
    shared tool-calling payload consumed by ``run_agent_tool_calling_round``.
    """
    model = params.get("model", "claude-sonnet-4-5")
    messages = params.get("messages") or []
    tools = params.get("tools") or []
    temperature = params.get("temperature", 0.3)
    is_sonnet_5 = model == CLAUDE_SONNET_5_MODEL

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("claude_chat_completion_with_tools called without messages")
        return {"content": None, "tool_calls": None, "assistant_message": None}

    try:
        client = get_claude_async_client()
        system_content, claude_messages = chat_messages_to_claude_messages(messages)
        api_params: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            "tools": convert_openai_tools_to_claude(tools),
            "max_tokens": (
                CLAUDE_SONNET_5_DEFAULT_MAX_TOKENS
                if is_sonnet_5
                else CLAUDE_TOOL_CALLING_DEFAULT_MAX_TOKENS
            ),
        }
        if not is_sonnet_5:
            api_params["temperature"] = temperature
        if system_content.strip():
            api_params["system"] = system_content.strip()

        response = await client.messages.create(**api_params)
        parsed = parse_claude_tool_response(response)
        logger.debug(
            f"Claude tool completion model={model}, "
            f"tool_calls={len(parsed.get('tool_calls') or [])}"
        )
        return parsed
    except Exception as e:
        logger.error(f"Error calling Claude tool completion: {e}", exc_info=True)
        raise

