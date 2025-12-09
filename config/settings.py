from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
import tomllib

def _get_version_from_pyproject() -> str:
    """Read version from pyproject.toml"""
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
        return data["project"]["version"]

class Settings(BaseSettings):
    PROJECT_TITLE: str = "elysium-agents"
    PROJECT_VERSION: str = _get_version_from_pyproject()
    PORT: int = 7000
    RELOAD: bool = Field(default=True)  # Pydantic will handle type conversion
    HOST: str = "0.0.0.0"
    ENVIRONMENT: str
    WORKERS: int = 2
    MONGO_URI: str
    MONGO_DB_NAME: str
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str
    JWT_SECRET: str
    APPLICATION_PASSKEY: str
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)
    QDRANT_CLUSTER_ENDPOINT:str
    QDRANT_API_KEY:str
    OPENAI_API_KEY:str
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"

settings = Settings()
