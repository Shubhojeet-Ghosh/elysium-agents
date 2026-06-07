from typing import Any, Dict

from services.email_agent_services.gmail_api_services import refresh_access_token
from services.email_agent_services.gmail_oauth_services import get_gmail_account_by_id


async def get_gmail_access_token_for_account(gmail_account_id: str) -> Dict[str, Any]:
    """Refresh and return a Gmail access token for the linked inbox account."""
    normalized_account_id = (gmail_account_id or "").strip()
    if not normalized_account_id:
        return {
            "success": False,
            "message": "gmail_account_id is required.",
        }

    account = await get_gmail_account_by_id(normalized_account_id)
    if not account:
        return {
            "success": False,
            "message": "Gmail account not found.",
        }

    if (account.get("status") or "").strip().lower() == "revoked":
        return {
            "success": False,
            "message": "Gmail account is disconnected. Reconnect the inbox.",
        }

    refresh_token = (account.get("refresh_token") or "").strip()
    if not refresh_token:
        return {
            "success": False,
            "message": "Gmail account is missing a refresh token. Reconnect the inbox.",
        }

    token_result = await refresh_access_token(refresh_token)
    if not token_result.get("success"):
        return {
            "success": False,
            "message": token_result.get("message", "Failed to refresh Gmail access token."),
            "details": token_result.get("details"),
        }

    access_token = (token_result.get("data") or {}).get("access_token", "").strip()
    if not access_token:
        return {
            "success": False,
            "message": "Google did not return an access token.",
        }

    return {
        "success": True,
        "access_token": access_token,
        "email_address": (account.get("email_address") or "").strip(),
        "display_name": (account.get("display_name") or "").strip(),
        "gmail_account_id": normalized_account_id,
    }
