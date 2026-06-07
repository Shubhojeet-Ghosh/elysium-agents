from pydantic import BaseModel, Field


class GetTicketStatusRequest(BaseModel):
    ticket_number: str = Field(..., min_length=1, max_length=64)
