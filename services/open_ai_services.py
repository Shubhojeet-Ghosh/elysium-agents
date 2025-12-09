from typing import List, Optional, Dict, Any, AsyncGenerator, Union
from openai import AsyncOpenAI
from logging_config import get_logger
from config.settings import settings

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