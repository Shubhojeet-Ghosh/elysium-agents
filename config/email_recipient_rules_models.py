from typing import List

from pydantic import BaseModel, Field, model_validator


class CreateEmailRecipientRuleRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    rule_name: str = Field(..., min_length=1, max_length=256)
    recipient_prompt: str = Field(..., min_length=1, max_length=10_000)
    cc_user_ids: List[str] = Field(default_factory=list, max_length=20)
    bcc_user_ids: List[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_recipient_lists(self):
        if not self.cc_user_ids and not self.bcc_user_ids:
            raise ValueError("At least one cc_user_id or bcc_user_id is required.")
        return self


class UpdateEmailRecipientRuleRequest(BaseModel):
    recipient_rule_id: str = Field(..., min_length=1, max_length=128)
    team_id: str = Field(..., min_length=1, max_length=128)
    rule_name: str = Field(..., min_length=1, max_length=256)
    recipient_prompt: str = Field(..., min_length=1, max_length=10_000)
    cc_user_ids: List[str] = Field(default_factory=list, max_length=20)
    bcc_user_ids: List[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_recipient_lists(self):
        if not self.cc_user_ids and not self.bcc_user_ids:
            raise ValueError("At least one cc_user_id or bcc_user_id is required.")
        return self


class ListTeamEmailRecipientRulesRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
