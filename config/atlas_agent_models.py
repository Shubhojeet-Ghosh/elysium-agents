from pydantic import BaseModel, ConfigDict, Field


class ListAgentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=100)
