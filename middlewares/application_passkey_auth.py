from fastapi import Header, Request
from typing import Optional

from config.settings import settings
from logging_config import get_logger

logger = get_logger()

async def verify_application_passkey(
    request: Request,
    x_application_passkey: Optional[str] = Header(default=None, convert_underscores=True)
) -> bool:
    """
    Verify passkey from header with underscore OR hyphen.
    """

    # Try standard hyphen header first
    key = x_application_passkey

    # If not found, try underscore header manually
    if not key:
        key = request.headers.get("X_Application_Passkey")

    if not key:
        logger.warning("Missing X-Application-Passkey header")
        return False

    if key == settings.APPLICATION_PASSKEY:
        return True

    logger.warning("Invalid X-Application-Passkey header provided")
    return False
