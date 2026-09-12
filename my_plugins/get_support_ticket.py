import httpx

PLUGIN_NAME = "get_support_ticket"
PLUGIN_DISPLAY_NAME = "Get Support Ticket"
PLUGIN_DESCRIPTION = (
    "Use when the user asks about a support ticket in any way: status, updates, replies, "
    "subject, description, progress, or whether something changed. Always call this tool "
    "again on every ticket-related request even if ticket details already appear in the "
    "conversation history or a previous tool result — including when the user says to "
    "check again, recheck, refresh, look it up again, or asks anything new about the same "
    "ticket. Requires ticket_number in the request body."
)

GET_TICKET_URL = (
    "https://ai.sgdevstudio.in/elysium-agents/elysium-atlas/support-tickets/v1/get-ticket"
)


class PluginInputs:
    ticket_number = {
        "type": "string",
        "description": (
            "The full support ticket number to look up. Format: TKT-{year}-{mongo_id}. "
            "Do not pass Mongo ticket_id alone without the TKT-{year}- prefix. On every "
            "user request about this ticket — including check again, recheck, refresh, "
            "status updates, replies, or any follow-up — the tool must be called again "
            "with this parameter even if ticket data is already in the conversation or "
            "prior tool results."
        ),
        "required": True,
    }


def run(inputs: dict, secrets):
    ticket_number = (inputs.get("ticket_number") or "").strip()
    if not ticket_number:
        return {"error": True, "message": "ticket_number is required."}

    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            GET_TICKET_URL,
            json={"ticket_number": ticket_number},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    try:
        body = response.json()
    except Exception:
        body = response.text or ""

    if response.status_code >= 400:
        return {
            "error": True,
            "status_code": response.status_code,
            "body": body,
        }

    return body if isinstance(body, dict) else {"result": body}
