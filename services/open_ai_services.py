from typing import List, Optional
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

