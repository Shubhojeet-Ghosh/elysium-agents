from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TicketStatus = Literal[
    "open",
    "in_progress",
    "waiting_on_customer",
    "resolved",
    "closed",
]

TICKET_STATUS_VALUES: tuple[str, ...] = (
    "open",
    "in_progress",
    "waiting_on_customer",
    "resolved",
    "closed",
)


class CreateSupportTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=10000)


class ListMySupportTicketsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    status: TicketStatus | None = None


class GetSupportTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_number: str = Field(..., min_length=1, max_length=64)


class InternalUpdateSupportTicketRequest(BaseModel):
    """Internal-only update via APPLICATION_PASSKEY (Postman / superuser tooling)."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: str | None = Field(default=None, min_length=1)
    ticket_number: str | None = Field(default=None, min_length=1, max_length=64)
    status: TicketStatus | None = None
    comment: str | None = Field(default=None, min_length=1, max_length=10000)

    @model_validator(mode="after")
    def validate_identifiers_and_payload(self) -> "InternalUpdateSupportTicketRequest":
        if not self.ticket_id and not self.ticket_number:
            raise ValueError("Either ticket_id or ticket_number is required.")
        if self.status is None and self.comment is None:
            raise ValueError("At least one of status or comment must be provided.")
        return self
