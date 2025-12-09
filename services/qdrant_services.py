from qdrant_client import AsyncQdrantClient
from logging_config import get_logger
from config.settings import settings

logger = get_logger()

# Module-level Qdrant client (initialized during application startup)
qdrant_client: AsyncQdrantClient = None


async def get_qdrant_client() -> AsyncQdrantClient:
    """
    Initialize and configure the Qdrant client.
    Raises an exception if Qdrant is unavailable - server will not start without Qdrant.
    
    Returns:
        AsyncQdrantClient: Configured Qdrant client
        
    Raises:
        Exception: If unable to connect to Qdrant server
    """
    try:
        client = AsyncQdrantClient(
            url=settings.QDRANT_CLUSTER_ENDPOINT,
            api_key=settings.QDRANT_API_KEY,
            timeout=10  # 10 second timeout
        )
        # Test connection by getting collections list
        await client.get_collections()
        logger.info(f"Connected to Qdrant successfully at {settings.QDRANT_CLUSTER_ENDPOINT}")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant at {settings.QDRANT_CLUSTER_ENDPOINT}: {e}")
        raise


async def initialize_qdrant_client():
    """
    Initialize the Qdrant client connection.
    This should be called during application startup.
    Raises an exception if Qdrant is unavailable - server will not start without Qdrant.
    
    Raises:
        RuntimeError: If unable to connect to Qdrant server
    """
    global qdrant_client
    try:
        qdrant_client = await get_qdrant_client()
        # logger.info("Qdrant client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Qdrant connection. Server cannot start without Qdrant.")
        raise RuntimeError(f"Qdrant connection failed: {e}. Server requires Qdrant to be running.") from e


async def close_qdrant_client():
    """
    Close the Qdrant client connection.
    This should be called during application shutdown.
    """
    global qdrant_client
    if qdrant_client is not None:
        try:
            await qdrant_client.close()
            logger.info("Qdrant client connection closed.")
        except Exception as e:
            logger.warning(f"Error closing Qdrant client: {e}")
        finally:
            qdrant_client = None


def get_qdrant_client_instance() -> AsyncQdrantClient:
    """
    Get the initialized Qdrant client instance.
    
    Returns:
        AsyncQdrantClient: Qdrant client instance for async operations
        
    Raises:
        RuntimeError: If Qdrant client is not initialized
    """
    if qdrant_client is None:
        raise RuntimeError("Qdrant client is not initialized. Call initialize_qdrant_client() first.")
    
    return qdrant_client

