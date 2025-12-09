from motor.motor_asyncio import AsyncIOMotorClient
from motor.motor_asyncio import AsyncIOMotorDatabase
from motor.motor_asyncio import AsyncIOMotorCollection
from logging_config import get_logger
from config.settings import settings

logger = get_logger()

# Module-level MongoDB client and database (initialized during application startup)
mongo_client: AsyncIOMotorClient = None
mongo_db: AsyncIOMotorDatabase = None


async def get_mongo_client() -> AsyncIOMotorClient:
    """
    Initialize and configure the MongoDB client.
    Raises an exception if MongoDB is unavailable - server will not start without MongoDB.
    
    Returns:
        AsyncIOMotorClient: Configured MongoDB client
        
    Raises:
        Exception: If unable to connect to MongoDB server
    """
    try:
        client = AsyncIOMotorClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=5000  # 5 second timeout
        )
        # Test connection by accessing server info
        await client.server_info()
        logger.info(f"Connected to MongoDB successfully.")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB at {settings.MONGO_URI}: {e}")
        raise


async def initialize_mongo_client():
    """
    Initialize the MongoDB client connection and database.
    This should be called during application startup.
    Raises an exception if MongoDB is unavailable - server will not start without MongoDB.
    
    Raises:
        RuntimeError: If unable to connect to MongoDB server
    """
    global mongo_client, mongo_db
    try:
        mongo_client = await get_mongo_client()
        mongo_db = mongo_client[settings.MONGO_DB_NAME]
        logger.info(f"MongoDB database '{settings.MONGO_DB_NAME}' initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize MongoDB connection. Server cannot start without MongoDB.")
        raise RuntimeError(f"MongoDB connection failed: {e}. Server requires MongoDB to be running.") from e


async def close_mongo_client():
    """
    Close the MongoDB client connection.
    This should be called during application shutdown.
    """
    global mongo_client, mongo_db
    if mongo_client is not None:
        try:
            mongo_client.close()
            logger.info("MongoDB client connection closed.")
        except Exception as e:
            logger.warning(f"Error closing MongoDB client: {e}")
        finally:
            mongo_client = None
            mongo_db = None


def get_collection(collection_name: str) -> AsyncIOMotorCollection:
    """
    Get a MongoDB collection instance by collection name.
    
    Args:
        collection_name: Name of the collection to retrieve
        
    Returns:
        AsyncIOMotorCollection: MongoDB collection instance for async operations
        
    Raises:
        RuntimeError: If MongoDB client is not initialized
    """
    if mongo_db is None:
        raise RuntimeError("MongoDB client is not initialized. Call initialize_mongo_client() first.")
    
    try:
        return mongo_db[collection_name]
    except Exception as e:
        logger.error(f"Failed to get collection '{collection_name}': {e}")
        raise

