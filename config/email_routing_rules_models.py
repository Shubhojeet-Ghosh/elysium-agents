from typing import Literal

from pydantic import BaseModel, Field


class CreateEmailRoutingRuleRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    department_id: str = Field(..., min_length=1, max_length=128)
    rule_name: str = Field(..., min_length=1, max_length=256)
    routing_prompt: str = Field(..., min_length=1, max_length=10_000)
    priority: int = Field(default=100, ge=1, le=10_000)
    is_fallback: bool = Field(default=False)


class UpdateEmailRoutingRuleRequest(BaseModel):
    routing_rule_id: str = Field(..., min_length=1, max_length=128)
    team_id: str = Field(..., min_length=1, max_length=128)
    department_id: str = Field(..., min_length=1, max_length=128)
    rule_name: str = Field(..., min_length=1, max_length=256)
    routing_prompt: str = Field(..., min_length=1, max_length=10_000)
    priority: int = Field(default=100, ge=1, le=10_000)
    is_fallback: bool = Field(default=False)
    status: Literal["active", "inactive"] = Field(default="active")


class ListTeamEmailRoutingRulesRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    include_inactive: bool = Field(default=False)


class DeleteEmailRoutingRuleRequest(BaseModel):
    routing_rule_id: str = Field(..., min_length=1, max_length=128)
