from pydantic import BaseModel, Field


class GetTicketStatusRequest(BaseModel):
    ticket_number: str = Field(..., min_length=1, max_length=64)


class CreateTicketRequest(BaseModel):
    issue_description: str = Field(..., min_length=1)
