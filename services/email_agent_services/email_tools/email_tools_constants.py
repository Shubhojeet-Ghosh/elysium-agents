from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EMAIL_TICKET_STATUS_JSON_PATH = PROJECT_ROOT / "constants" / "email_ticket_status.json"

TICKET_NUMBER_PREFIX = "TKT-"
DEFAULT_NEW_TICKET_STATUS = "open"
DEFAULT_NEW_TICKET_REMARKS = (
    "Your support ticket has been created. A team member will review your request "
    "and respond shortly."
)
NEW_TICKET_RESOLUTION_DAYS = 7
