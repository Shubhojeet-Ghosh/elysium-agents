from typing import List, Literal

from pydantic import BaseModel, Field


class AgentReplyActionConfig(BaseModel):
    """How the agent delivers AI-generated replies after flow processing."""

    mode: Literal["draft", "auto_send"] = Field(
        default="draft",
        description=(
            "draft — save reply as a Gmail draft on the thread; "
            "auto_send — send the reply when model confidence >= auto_send_min_confidence, else draft"
        ),
    )
    auto_send_min_confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence (0–1) required to auto-send when mode is auto_send.",
    )


class CreateEmailAiAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    gmail_account_id: str = Field(..., min_length=1, max_length=128)
    system_prompt: str = Field(..., min_length=1, max_length=20_000)
    email_format_template: str = Field(
        default="",
        max_length=10_000,
        description=(
            "Optional template describing how AI-generated reply emails should be formatted "
            "(structure, tone, sections). Used by the Generate Email flow node."
        ),
    )
    knowledge_id: str = Field(..., min_length=1, max_length=128)
    tool_ids: List[str] = Field(default_factory=list, max_length=20)
    llm_model: str = Field(..., min_length=1, max_length=128)
    reply_action: AgentReplyActionConfig = Field(default_factory=AgentReplyActionConfig)
    routing_rule_ids: List[str] = Field(default_factory=list, max_length=50)
    recipient_rule_ids: List[str] = Field(default_factory=list, max_length=50)
    flow_id: str = Field(
        default="",
        max_length=128,
        description=(
            "Optional existing team workflow to attach. "
            "Leave empty to auto-create a new default workflow."
        ),
    )


class GetEmailAiAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)


class UpdateEmailAiAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)
    gmail_account_id: str = Field(..., min_length=1, max_length=128)
    system_prompt: str = Field(..., min_length=1, max_length=20_000)
    email_format_template: str = Field(
        default="",
        max_length=10_000,
        description=(
            "Optional template describing how AI-generated reply emails should be formatted "
            "(structure, tone, sections). Used by the Generate Email flow node."
        ),
    )
    knowledge_id: str = Field(..., min_length=1, max_length=128)
    tool_ids: List[str] = Field(default_factory=list, max_length=20)
    llm_model: str = Field(..., min_length=1, max_length=128)
    reply_action: AgentReplyActionConfig = Field(default_factory=AgentReplyActionConfig)
    routing_rule_ids: List[str] = Field(default_factory=list, max_length=50)
    recipient_rule_ids: List[str] = Field(default_factory=list, max_length=50)
    flow_id: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Attach a different team workflow to this agent. "
            "Omit to keep the current link. Must not already be attached to another agent."
        ),
    )


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


class SendThreadAiDraftRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    thread_id: str = Field(..., min_length=1, max_length=256)
