from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.human_handover_config import HANDOVER_TRIGGER_PROMPT_MAX_LENGTH


class GetHumanHandoverConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)


class UpdateHumanHandoverConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    enable_human_handover: bool | None = None
    handover_trigger_prompt: str | None = None

    @field_validator("handover_trigger_prompt")
    @classmethod
    def validate_handover_trigger_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            return ""
        if len(normalized) > HANDOVER_TRIGGER_PROMPT_MAX_LENGTH:
            raise ValueError(
                f"handover_trigger_prompt must be at most {HANDOVER_TRIGGER_PROMPT_MAX_LENGTH} characters."
            )
        return normalized


class ResetHumanHandoverConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)


class VisitorHandoverContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    chat_session_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=320)


class VisitorHandoverContactDeclineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    chat_session_id: str = Field(..., min_length=1)


def build_partial_human_handover_config_from_request(
    body: UpdateHumanHandoverConfigRequest,
) -> dict:
    partial: dict = {}
    if body.enable_human_handover is not None:
        partial["enable_human_handover"] = body.enable_human_handover
    if body.handover_trigger_prompt is not None:
        partial["handover_trigger_prompt"] = body.handover_trigger_prompt
    return partial
