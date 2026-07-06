from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.lead_collection_config import (
    COLLECTION_TRIGGER_PROMPT_MAX_LENGTH,
    MAX_LEAD_COLLECTION_FIELDS,
    MIN_MESSAGES_BEFORE_ASK_MAX,
    MIN_MESSAGES_BEFORE_ASK_MIN,
)

LeadFieldKey = Literal["email", "name", "phone", "company", "interest"]


class LeadCollectionFieldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: LeadFieldKey
    required: bool = False
    order: int = Field(..., ge=1)


class GetLeadCollectionConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)


class UpdateLeadCollectionConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    enable_lead_capturing: bool | None = None
    collection_trigger_prompt: str | None = None
    min_messages_before_ask: int | None = Field(default=None, ge=MIN_MESSAGES_BEFORE_ASK_MIN, le=MIN_MESSAGES_BEFORE_ASK_MAX)
    fields: list[LeadCollectionFieldInput] | None = Field(default=None, max_length=MAX_LEAD_COLLECTION_FIELDS)

    @field_validator("collection_trigger_prompt")
    @classmethod
    def validate_collection_trigger_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            return ""
        if len(normalized) > COLLECTION_TRIGGER_PROMPT_MAX_LENGTH:
            raise ValueError(
                f"collection_trigger_prompt must be at most {COLLECTION_TRIGGER_PROMPT_MAX_LENGTH} characters."
            )
        return normalized

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[LeadCollectionFieldInput] | None) -> list[LeadCollectionFieldInput] | None:
        if value is None:
            return value

        orders = [field.order for field in value]
        if len(orders) != len(set(orders)):
            raise ValueError("fields must have unique order values.")

        keys = [field.key for field in value]
        if len(keys) != len(set(keys)):
            raise ValueError("fields must have unique key values.")

        return value


class ResetLeadCollectionConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)


class UpdateSessionLeadRequest(BaseModel):
    """Partial update of captured lead fields for a chat session (human agent manual edit)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., min_length=1)
    chat_session_id: str = Field(..., min_length=1)
    fields: dict[LeadFieldKey, str | None] = Field(
        ...,
        min_length=1,
        description="Field key → value. Omit keys to leave unchanged. Pass null or empty string to clear.",
    )


def build_partial_lead_collection_config_from_request(
    body: UpdateLeadCollectionConfigRequest,
) -> dict:
    partial: dict = {}
    if body.enable_lead_capturing is not None:
        partial["enable_lead_capturing"] = body.enable_lead_capturing
    if body.collection_trigger_prompt is not None:
        partial["collection_trigger_prompt"] = body.collection_trigger_prompt
    if body.min_messages_before_ask is not None:
        partial["min_messages_before_ask"] = body.min_messages_before_ask
    if body.fields is not None:
        partial["fields"] = [field.model_dump() for field in body.fields]
    return partial
