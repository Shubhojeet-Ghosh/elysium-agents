from typing import List, Literal

from pydantic import BaseModel, Field


class ToolInputDefinition(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: Literal["string", "number", "integer", "boolean"] = "string"
    description: str = Field(..., min_length=1, max_length=500)
    required: bool = False


class CreateEmailToolDefinitionRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=2000)
    endpoint_url: str = Field(..., min_length=1, max_length=2000)
    http_method: Literal["GET", "POST", "get", "post"]
    inputs: List[ToolInputDefinition] = Field(default_factory=list)


class ListTeamEmailToolDefinitionsRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)


class DeleteEmailToolDefinitionRequest(BaseModel):
    tool_id: str = Field(..., min_length=1, max_length=128)
