from typing import Dict, Any, Optional, AsyncGenerator, Union

from groq import AsyncGroq

from config.settings import settings
from logging_config import get_logger

logger = get_logger()

# Singleton client
_groq_client: Optional[AsyncGroq] = None


def get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _groq_client


async def groq_chat_completions(params: Dict[str, Any]) -> Union[str, AsyncGenerator[str, None]]:
    """
    Simple Groq chat completion.

    Args:
        params: dict with keys:
            - model (str): defaults to "openai/gpt-oss-120b"
            - messages (list, required): chat messages
            - temperature (float, optional)
            - stream (bool, optional): if True, uses streaming responses

    Returns:
        str (non-stream) or async generator of str (stream)
    """
    model = params.get("model", "openai/gpt-oss-120b")
    messages = params.get("messages") or []
    temperature = params.get("temperature")
    stream = bool(params.get("stream", False))

    if not isinstance(messages, list) or len(messages) == 0:
        logger.warning("groq_chat_completions called without messages; returning empty string")
        return ""

    try:
        client = get_groq_client()
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

            logger.debug(f"Groq chat completion using model={model}, stream=True")
            return stream_generator()

        content = response.choices[0].message.content if response.choices else ""

        logger.debug(f"Groq chat completion using model={model}, stream=False")
        return content or ""
    except Exception as e:
        logger.error(f"Error calling Groq chat completion: {e}")
        raise

