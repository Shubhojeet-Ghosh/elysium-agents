from fastapi import APIRouter

from config.email_tools_models import GetTicketStatusRequest
from controllers.email_agent_controller_files.email_tools_controllers import (
    create_ticket_controller,
    get_ticket_status_controller,
    list_tickets_controller,
)

email_tools_router = APIRouter(
    prefix="/email-tools",
    tags=["Email Tools"],
)


@email_tools_router.post("/v1/get-ticket-status")
async def get_ticket_status_route(request_data: GetTicketStatusRequest):
    """Tool API: look up ticket status by ticket number. Public — no JWT required."""
    return await get_ticket_status_controller(request_data)


@email_tools_router.get("/v1/create-ticket")
async def create_ticket_route():
    """Tool API: create a new open ticket in constants JSON. No input required."""
    return await create_ticket_controller()


@email_tools_router.get("/v1/list-tickets")
async def list_tickets_route():
    """List all tickets from constants JSON. No pagination — MVP."""
    return await list_tickets_controller()
