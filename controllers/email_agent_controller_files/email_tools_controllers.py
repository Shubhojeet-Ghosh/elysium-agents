from fastapi.responses import JSONResponse

from config.email_tools_models import GetTicketStatusRequest
from logging_config import get_logger
from services.email_agent_services.email_tools.ticket_status_services import (
    create_ticket,
    get_ticket_status_by_ticket_number,
    list_all_tickets,
)

logger = get_logger()


async def get_ticket_status_controller(request_data: GetTicketStatusRequest):
    try:
        result = await get_ticket_status_by_ticket_number(
            ticket_number=request_data.ticket_number
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch ticket status."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "ticket": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in get_ticket_status_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching ticket status.",
            },
        )


async def create_ticket_controller():
    try:
        result = await create_ticket()
        status_code = result.get("status_code", 201 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to create ticket."),
                },
            )

        data = result.get("data", {})
        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "ticket_number": data.get("ticket_number"),
                "status": data.get("status"),
                "expected_resolution_due_date": data.get("expected_resolution_due_date"),
                "created_at": data.get("created_at"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_ticket_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while creating the ticket.",
            },
        )


async def list_tickets_controller():
    try:
        result = await list_all_tickets()
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to list tickets."),
                },
            )

        data = result.get("data", {})
        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "count": data.get("count"),
                "tickets": data.get("tickets"),
            },
        )

    except Exception as e:
        logger.error(f"Error in list_tickets_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while listing tickets.",
            },
        )
