from fastapi.responses import JSONResponse

from config.atlas_support_ticket_models import (
    CreateSupportTicketRequest,
    GetSupportTicketRequest,
    InternalUpdateSupportTicketRequest,
    ListMySupportTicketsRequest,
)
from logging_config import get_logger
from services.elysium_atlas_services.atlas_support_ticket_services import (
    create_support_ticket,
    get_support_ticket_by_number,
    internal_update_support_ticket,
    list_my_support_tickets,
)
from services.elysium_atlas_services.team_auth_services import (
    is_user_member_of_team,
    parse_session_team_context,
)

logger = get_logger()


def _unauthenticated_response(user_data: dict | None) -> JSONResponse | None:
    if user_data is None or user_data.get("success") is False:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": (user_data or {}).get("message", "Unauthorized")},
        )
    return None


def _no_team_context_response(user_data: dict) -> JSONResponse:
    if not user_data.get("user_id"):
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})
    return JSONResponse(
        status_code=403,
        content={"success": False, "message": "No team context. Select a team to continue."},
    )


async def _require_team_member(user_data: dict) -> tuple[str, str] | JSONResponse:
    auth_error = _unauthenticated_response(user_data)
    if auth_error:
        return auth_error

    session_context = parse_session_team_context(user_data)
    if session_context is None:
        return _no_team_context_response(user_data)

    user_id, team_id = session_context
    if not await is_user_member_of_team(user_id, team_id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "You are not a member of this team."},
        )
    return user_id, team_id


async def create_support_ticket_controller(
    body: CreateSupportTicketRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        team_member = await _require_team_member(user_data)
        if isinstance(team_member, JSONResponse):
            return team_member

        user_id, team_id = team_member
        result = await create_support_ticket(team_id, user_id, body)
        return JSONResponse(status_code=200, content={"success": True, "ticket": result["ticket"]})
    except Exception as e:
        logger.error(f"Error in create_support_ticket_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while creating the support ticket."},
        )


async def list_my_support_tickets_controller(
    body: ListMySupportTicketsRequest,
    user_data: dict,
) -> JSONResponse:
    try:
        team_member = await _require_team_member(user_data)
        if isinstance(team_member, JSONResponse):
            return team_member

        user_id, team_id = team_member
        result = await list_my_support_tickets(
            team_id=team_id,
            user_id=user_id,
            page=body.page,
            limit=body.limit,
            status=body.status,
        )
        return JSONResponse(status_code=200, content=result)
    except Exception as e:
        logger.error(f"Error in list_my_support_tickets_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while listing support tickets."},
        )


async def get_support_ticket_controller(body: GetSupportTicketRequest) -> JSONResponse:
    try:
        ticket = await get_support_ticket_by_number(body.ticket_number)
        if not ticket:
            return JSONResponse(status_code=404, content={"success": False, "message": "Ticket not found."})

        return JSONResponse(status_code=200, content={"success": True, "ticket": ticket})
    except Exception as e:
        logger.error(
            f"Error in get_support_ticket_controller for ticket_number={body.ticket_number}: {e}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching the support ticket."},
        )


async def internal_update_support_ticket_controller(
    body: InternalUpdateSupportTicketRequest,
    authorized: bool,
) -> JSONResponse:
    try:
        if not authorized:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "You are unauthorized to access this resource."},
            )

        result = await internal_update_support_ticket(body)
        if not result.get("success"):
            status_code = result.get("status_code", 400)
            return JSONResponse(status_code=status_code, content={"success": False, "message": result["message"]})

        return JSONResponse(status_code=200, content={"success": True, "ticket": result["ticket"]})
    except Exception as e:
        logger.error(f"Error in internal_update_support_ticket_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while updating the support ticket."},
        )
