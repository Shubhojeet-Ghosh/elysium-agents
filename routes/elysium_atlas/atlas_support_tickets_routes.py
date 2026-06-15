from fastapi import APIRouter, Depends

from config.atlas_support_ticket_models import (
    CreateSupportTicketRequest,
    GetSupportTicketRequest,
    InternalUpdateSupportTicketRequest,
    ListMySupportTicketsRequest,
)
from controllers.elysium_atlas_controller_files.atlas_support_ticket_controllers import (
    create_support_ticket_controller,
    get_support_ticket_controller,
    internal_update_support_ticket_controller,
    list_my_support_tickets_controller,
)
from middlewares.application_passkey_auth import verify_application_passkey
from middlewares.jwt_middleware import authorize_user

atlas_support_tickets_router = APIRouter(
    prefix="/elysium-atlas/support-tickets",
    tags=["Elysium Atlas - Support Tickets"],
)


@atlas_support_tickets_router.post("/v1/create-ticket")
async def create_support_ticket_route(
    body: CreateSupportTicketRequest,
    user: dict = Depends(authorize_user),
):
    return await create_support_ticket_controller(body, user)


@atlas_support_tickets_router.post("/v1/list-my-tickets")
async def list_my_support_tickets_route(
    body: ListMySupportTicketsRequest,
    user: dict = Depends(authorize_user),
):
    return await list_my_support_tickets_controller(body, user)


@atlas_support_tickets_router.post("/v1/get-ticket")
async def get_support_ticket_route(body: GetSupportTicketRequest):
    return await get_support_ticket_controller(body)


@atlas_support_tickets_router.post("/v1/internal/update-ticket")
async def internal_update_support_ticket_route(
    body: InternalUpdateSupportTicketRequest,
    authorized: bool = Depends(verify_application_passkey),
):
    return await internal_update_support_ticket_controller(body, authorized)
