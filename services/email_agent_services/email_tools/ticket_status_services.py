import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from logging_config import get_logger
from services.email_agent_services.email_tools.email_tools_constants import (
    DEFAULT_NEW_TICKET_REMARKS,
    DEFAULT_NEW_TICKET_STATUS,
    EMAIL_TICKET_STATUS_JSON_PATH,
    NEW_TICKET_RESOLUTION_DAYS,
    TICKET_NUMBER_PREFIX,
)

logger = get_logger()

_TICKET_NUMBER_PATTERN = re.compile(rf"^{re.escape(TICKET_NUMBER_PREFIX)}(\d+)$")


def _load_ticket_status_data() -> Dict[str, Any]:
    with open(EMAIL_TICKET_STATUS_JSON_PATH, encoding="utf-8") as file:
        return json.load(file)


def _save_ticket_status_data(data: Dict[str, Any]) -> None:
    with open(EMAIL_TICKET_STATUS_JSON_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def _generate_next_ticket_number(tickets: Dict[str, Any]) -> str:
    max_number = 1000
    for ticket_number in tickets:
        match = _TICKET_NUMBER_PATTERN.match(ticket_number.upper())
        if match:
            max_number = max(max_number, int(match.group(1)))

    return f"{TICKET_NUMBER_PREFIX}{max_number + 1}"


def _normalize_ticket_number(ticket_number: str) -> str:
    return ticket_number.strip().upper()


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_ticket(ticket_number: str, ticket: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ticket_number": ticket_number,
        "status": ticket.get("status", ""),
        "remarks": ticket.get("remarks", ""),
        "expected_resolution_due_date": ticket.get("expected_resolution_due_date", ""),
        "created_at": ticket.get("created_at", ""),
    }


async def get_ticket_status_by_ticket_number(ticket_number: str) -> Dict[str, Any]:
    """Look up ticket status by ticket number from the constants JSON file."""
    normalized_ticket_number = _normalize_ticket_number(ticket_number)

    if not normalized_ticket_number:
        return {
            "success": False,
            "status_code": 400,
            "message": "ticket_number cannot be empty.",
        }

    try:
        data = _load_ticket_status_data()
        tickets = data.get("tickets", {})
        ticket = tickets.get(normalized_ticket_number)

        if not ticket:
            return {
                "success": False,
                "status_code": 404,
                "message": "No ticket found for this ticket number.",
            }

        return {
            "success": True,
            "status_code": 200,
            "message": "Ticket status fetched successfully.",
            "data": _format_ticket(normalized_ticket_number, ticket),
        }

    except FileNotFoundError:
        logger.error(f"Ticket status JSON not found at {EMAIL_TICKET_STATUS_JSON_PATH}")
        return {
            "success": False,
            "status_code": 500,
            "message": "Ticket status data is unavailable.",
        }

    except json.JSONDecodeError as e:
        logger.error(f"Invalid ticket status JSON: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Ticket status data is misconfigured.",
        }

    except Exception as e:
        logger.error(
            f"Failed to fetch ticket status for {normalized_ticket_number}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch ticket status.",
        }


async def create_ticket() -> Dict[str, Any]:
    """Create a new open ticket in the constants JSON file with auto-generated ticket number."""
    try:
        data = _load_ticket_status_data()
        tickets = data.setdefault("tickets", {})

        ticket_number = _generate_next_ticket_number(tickets)
        created_at = _current_timestamp()
        expected_resolution_due_date = (
            date.today() + timedelta(days=NEW_TICKET_RESOLUTION_DAYS)
        ).isoformat()

        ticket = {
            "status": DEFAULT_NEW_TICKET_STATUS,
            "remarks": DEFAULT_NEW_TICKET_REMARKS,
            "expected_resolution_due_date": expected_resolution_due_date,
            "created_at": created_at,
        }

        tickets[ticket_number] = ticket
        _save_ticket_status_data(data)

        logger.info(f"Created ticket {ticket_number} with due date {expected_resolution_due_date}")

        return {
            "success": True,
            "status_code": 201,
            "message": "Ticket created successfully.",
            "data": _format_ticket(ticket_number, ticket),
        }

    except FileNotFoundError:
        logger.error(f"Ticket status JSON not found at {EMAIL_TICKET_STATUS_JSON_PATH}")
        return {
            "success": False,
            "status_code": 500,
            "message": "Ticket status data is unavailable.",
        }

    except json.JSONDecodeError as e:
        logger.error(f"Invalid ticket status JSON: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Ticket status data is misconfigured.",
        }

    except Exception as e:
        logger.error(f"Failed to create ticket: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create ticket.",
        }


async def list_all_tickets() -> Dict[str, Any]:
    """List all tickets from the constants JSON file."""
    try:
        data = _load_ticket_status_data()
        tickets = data.get("tickets", {})

        ticket_list: List[Dict[str, Any]] = [
            _format_ticket(ticket_number, ticket)
            for ticket_number, ticket in tickets.items()
        ]

        ticket_list.sort(key=lambda item: item.get("created_at", ""), reverse=True)

        logger.info(f"Listed {len(ticket_list)} tickets")

        return {
            "success": True,
            "status_code": 200,
            "message": "Tickets fetched successfully.",
            "data": {
                "count": len(ticket_list),
                "tickets": ticket_list,
            },
        }

    except FileNotFoundError:
        logger.error(f"Ticket status JSON not found at {EMAIL_TICKET_STATUS_JSON_PATH}")
        return {
            "success": False,
            "status_code": 500,
            "message": "Ticket status data is unavailable.",
        }

    except json.JSONDecodeError as e:
        logger.error(f"Invalid ticket status JSON: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Ticket status data is misconfigured.",
        }

    except Exception as e:
        logger.error(f"Failed to list tickets: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to list tickets.",
        }
