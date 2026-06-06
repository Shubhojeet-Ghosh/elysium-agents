from pydantic import BaseModel, Field


class CreateGmailAccountRequest(BaseModel):
    inbox_name: str = Field(..., min_length=1, max_length=256)
    code: str = Field(..., min_length=1, max_length=4096)


class ListTeamGmailAccountsRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
