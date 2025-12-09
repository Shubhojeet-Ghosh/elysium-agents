from typing import Optional

from fastapi import Header

from config.settings import settings
from logging_config import get_logger

logger = get_logger()


async def verify_application_passkey(
    x_application_passkey: Optional[str] = Header(default=None, convert_underscores=False)
) -> bool:
    """
    Dependency to verify the application passkey sent via header.

    Header:
        X-Application-Passkey: passkey string

    Returns:
        True if the header matches the configured passkey, else False.
    """
    if not x_application_passkey:
        logger.warning("Missing X-Application-Passkey header")
        return False

    if x_application_passkey == settings.APPLICATION_PASSKEY:
        return True

    logger.warning("Invalid X-Application-Passkey header provided")
    return False

