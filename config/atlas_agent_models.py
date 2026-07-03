from pydantic import BaseModel, ConfigDict, Field

from config.kb_item_constants import DEFAULT_KB_LIST_PAGE_SIZE, MAX_KB_LIST_PAGE_SIZE


class ListAgentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=100)


class AgentIdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)


class ListAgentAttachedKbItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=DEFAULT_KB_LIST_PAGE_SIZE, ge=1, le=MAX_KB_LIST_PAGE_SIZE)
