from pydantic import BaseModel, Field


class CreateEmailAiAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    gmail_account_id: str = Field(..., min_length=1, max_length=128)


class ListTeamEmailAiAgentsRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)


class TriggerAgentSyncRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)


class ListTeamEmailThreadsRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


class GetEmailThreadRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    thread_id: str = Field(..., min_length=1, max_length=256)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
