from typing import List, Optional, Dict, Any, AsyncGenerator, Union, Type, TypeVar
import asyncio
from xai_sdk import Client
from xai_sdk.chat import user, system
from pydantic import BaseModel
from logging_config import get_logger
from config.settings import settings

T = TypeVar('T', bound=BaseModel)

logger = get_logger()

# Initialize Grok client
_grok_client: Optional[Client] = None


def get_grok_client() -> Client:
    """
    Get or create the Grok client instance.
    Uses singleton pattern to reuse the client.
    
    Returns:
        Client: The Grok client instance
    """
    global _grok_client
    if _grok_client is None:
        _grok_client = Client(
            api_key=settings.XAI_API_KEY,
            timeout=3600  # Longer timeout for reasoning models
        )
    return _grok_client


async def grok_chat_completion(params: Dict[str, Any]) -> Union[str, AsyncGenerator[str, None]]:
    """
    General chat completion with Grok using xAI SDK.

    Args:
        params: Dictionary of parameters. Supported keys:
            - messages (list, required): Chat messages with 'role' and 'content'
            - model (str): Defaults to "grok-4"
            - temperature (float): Not directly supported in xAI SDK, logged as warning
            - stream (bool): Defaults to False, supports streaming

    Returns:
        str (non-stream) or async generator of str (stream)
    """
    model = params.get("model", "grok-4")
    messages = params.get("messages") or []
    temperature = params.get("temperature", 0.7)
    stream = bool(params.get("stream", False))

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("grok_chat_completion called without messages; returning empty string")
        return ""

    # Log unsupported params
    if temperature != 0.7:
        logger.warning(f"Temperature {temperature} not supported in xAI SDK")

    try:
        if stream:
            async def stream_generator() -> AsyncGenerator[str, None]:
                queue = asyncio.Queue()

                def producer():
                    try:
                        client = get_grok_client()
                        chat = client.chat.create(model=model)
                        for msg in messages:
                            role = msg.get('role')
                            content = msg.get('content', '')
                            if role == 'system':
                                chat.append(system(content))
                            elif role == 'user':
                                chat.append(user(content))
                            else:
                                logger.warning(f"Unsupported role {role}, skipping message")
                        for response, chunk in chat.stream():
                            queue.put_nowait(chunk.content)
                        queue.put_nowait(None)  # sentinel
                    except Exception as e:
                        queue.put_nowait(e)

                # Run producer in thread
                asyncio.create_task(asyncio.to_thread(producer))

                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    yield item

            logger.debug(f"Grok chat completion using model={model}, stream=True")
            return stream_generator()
        else:
            def sync_call():
                client = get_grok_client()
                chat = client.chat.create(model=model)
                for msg in messages:
                    role = msg.get('role')
                    content = msg.get('content', '')
                    if role == 'system':
                        chat.append(system(content))
                    elif role == 'user':
                        chat.append(user(content))
                    else:
                        logger.warning(f"Unsupported role {role}, skipping message")
                response = chat.sample()
                return response.content

            content = await asyncio.to_thread(sync_call)
            logger.debug(f"Grok chat completion using model={model}, stream=False")
            return content or ""
    except Exception as e:
        logger.error(f"Error calling Grok chat completion: {e}")
        raise


async def grok_structured_output(
    model: str,
    messages: List[Dict[str, str]],
    response_format: Type[T]
) -> Dict[str, Any]:
    """
    Get structured output from Grok using Pydantic BaseModel for parsing.
    Note: Uses OpenAI-compatible API for structured parsing, as xAI SDK may not support it directly.
    
    Args:
        model: The Grok model to use (e.g., "grok-4")
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
        
        result = await grok_structured_output(
            model="grok-4",
            messages=[
                {"role": "system", "content": "Extract research paper data."},
                {"role": "user", "content": "..."}
            ],
            response_format=ResearchPaperExtraction
        )
        ```
    """
    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("grok_structured_output called without messages")
        raise ValueError("Messages list cannot be empty")
    
    if not issubclass(response_format, BaseModel):
        logger.error("response_format must be a Pydantic BaseModel class")
        raise ValueError("response_format must be a Pydantic BaseModel class")
    
    try:
        # Use OpenAI-compatible client for structured output
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.XAI_API_KEY,
            base_url="https://api.x.ai/v1",
            timeout=3600
        )
        response = await client.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_format,
        )
        
        if not response.choices:
            logger.error("No choices returned from Grok API")
            raise ValueError("No choices returned from Grok API")
        
        parsed = response.choices[0].message.parsed
        if parsed is None:
            logger.error("Failed to parse structured output")
            raise ValueError("Failed to parse structured output")
        
        # Convert Pydantic model to dict (JSON-serializable)
        result = parsed.model_dump()
        logger.debug(f"Grok structured output parsed successfully using model={model}")
        return result
        
    except Exception as e:
        logger.error(f"Error calling Grok structured output parsing: {e}")
        raise