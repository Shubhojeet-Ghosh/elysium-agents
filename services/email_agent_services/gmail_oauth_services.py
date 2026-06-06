from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from bson import ObjectId
from bson.errors import InvalidId

from config.gmail_oauth_config import (
    GMAIL_OAUTH_SCOPES,
    GMAIL_PROFILE_URL,
    GOOGLE_REVOKE_URL,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
)
from config.settings import settings
from logging_config import get_logger
from services.mongo_services import get_collection

logger = get_logger()

GMAIL_ACCOUNTS_COLLECTION = "email-gmail_accounts"


def _format_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_gmail_account_id_str(account: Dict[str, Any]) -> str:
    return str(account["_id"])


def _serialize_gmail_account_public(account: Dict[str, Any]) -> Dict[str, Any]:
    """Map a gmail account document to a safe API response (no tokens)."""
    return {
        "account_id": get_gmail_account_id_str(account),
        "user_id": account.get("user_id", ""),
        "team_id": account.get("team_id", ""),
        "inbox_name": account.get("inbox_name", ""),
        "email_address": account.get("email_address", ""),
        "display_name": account.get("display_name", ""),
        "status": account.get("status", "active"),
        "connected_at": _format_datetime(account.get("created_at")),
        "updated_at": _format_datetime(account.get("updated_at")),
    }


async def get_gmail_account_by_id(gmail_account_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a Gmail account by MongoDB _id."""
    try:
        object_id = ObjectId(gmail_account_id.strip())
    except InvalidId:
        return None

    collection = get_collection(GMAIL_ACCOUNTS_COLLECTION)
    return await collection.find_one({"_id": object_id})


async def _exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    if not settings.GOOGLE_REDIRECT_URI:
        return {
            "success": False,
            "message": "GOOGLE_REDIRECT_URI is not configured on the server.",
        }

    payload = {
        "code": code.strip(),
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=payload)

    if response.status_code != 200:
        logger.error(f"Google token exchange failed: {response.status_code} {response.text}")
        return {
            "success": False,
            "message": "Failed to exchange Google authorization code.",
            "details": response.text,
        }

    token_data = response.json()
    if not token_data.get("refresh_token"):
        logger.warning("Google token response did not include a refresh_token")

    return {"success": True, "data": token_data}


async def _fetch_google_userinfo(access_token: str) -> Optional[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        logger.error(f"Google userinfo failed: {response.status_code} {response.text}")
        return None

    return response.json()


async def _fetch_gmail_profile(access_token: str) -> Optional[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            GMAIL_PROFILE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        logger.error(f"Gmail profile failed: {response.status_code} {response.text}")
        return None

    return response.json()


async def _revoke_google_token(token: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(GOOGLE_REVOKE_URL, params={"token": token})


async def create_gmail_account(
    user_id: str,
    team_id: str,
    inbox_name: str,
    code: str,
) -> Dict[str, Any]:
    """Exchange OAuth code and create or update a Gmail inbox account."""
    normalized_inbox_name = inbox_name.strip()
    normalized_team_id = team_id.strip()

    if not normalized_team_id:
        return {
            "success": False,
            "status_code": 400,
            "message": "team_id is required to create a Gmail inbox.",
        }

    try:
        token_result = await _exchange_code_for_tokens(code)
        if not token_result.get("success"):
            return {
                "success": False,
                "status_code": 400,
                "message": token_result.get("message", "Failed to exchange authorization code."),
            }

        token_data = token_result["data"]
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token:
            return {
                "success": False,
                "status_code": 400,
                "message": "Google did not return an access token.",
            }

        userinfo = await _fetch_google_userinfo(access_token)
        gmail_profile = await _fetch_gmail_profile(access_token)

        if not userinfo or not gmail_profile:
            return {
                "success": False,
                "status_code": 400,
                "message": "Failed to fetch Gmail account details from Google.",
            }

        email_address = gmail_profile.get("emailAddress") or userinfo.get("email", "")
        email_address = email_address.strip().lower()

        if not email_address:
            return {
                "success": False,
                "status_code": 400,
                "message": "Could not determine Gmail email address.",
            }

        if not refresh_token:
            return {
                "success": False,
                "status_code": 400,
                "message": "Google did not return a refresh token. Reconnect with prompt=consent and access_type=offline.",
            }

        now = datetime.now(timezone.utc)
        collection = get_collection(GMAIL_ACCOUNTS_COLLECTION)

        account_document = {
            "user_id": user_id,
            "team_id": normalized_team_id,
            "inbox_name": normalized_inbox_name,
            "provider": "gmail",
            "email_address": email_address,
            "google_subject_id": userinfo.get("sub", ""),
            "display_name": userinfo.get("name", ""),
            "scopes": GMAIL_OAUTH_SCOPES,
            "refresh_token": refresh_token,
            "status": "active",
            "last_token_refresh_at": now,
            "last_error": None,
            "updated_at": now,
        }

        existing_account = await collection.find_one({
            "user_id": user_id,
            "email_address": email_address,
        })

        if existing_account:
            await collection.update_one(
                {"_id": existing_account["_id"]},
                {"$set": account_document},
            )
            account_id = get_gmail_account_id_str(existing_account)
            status_code = 200
            message = "Gmail inbox updated successfully."
        else:
            account_document["created_at"] = now
            result = await collection.insert_one(account_document)
            account_id = str(result.inserted_id)
            status_code = 201
            message = "Gmail inbox created successfully."

        logger.info(f"Gmail account {account_id} linked for user {user_id}")

        return {
            "success": True,
            "status_code": status_code,
            "message": message,
            "data": {
                "account_id": account_id,
                "user_id": user_id,
                "team_id": normalized_team_id,
                "inbox_name": normalized_inbox_name,
                "email_address": email_address,
                "display_name": userinfo.get("name", ""),
                "status": "active",
                "created_at": _format_datetime(
                    existing_account.get("created_at") if existing_account else now
                ),
                "updated_at": now.isoformat(),
            },
        }

    except Exception as e:
        logger.error(f"Failed to create Gmail account for user {user_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create Gmail inbox account.",
        }


async def list_gmail_accounts(user_id: str) -> Dict[str, Any]:
    """List Gmail inbox accounts for a user. Never returns tokens."""
    try:
        collection = get_collection(GMAIL_ACCOUNTS_COLLECTION)
        cursor = collection.find({
            "user_id": user_id,
            "status": {"$ne": "revoked"},
        })

        accounts = []
        async for account in cursor:
            accounts.append(_serialize_gmail_account_public(account))

        return {
            "success": True,
            "status_code": 200,
            "message": "Gmail accounts fetched successfully.",
            "data": {
                "count": len(accounts),
                "accounts": accounts,
            },
        }

    except Exception as e:
        logger.error(f"Failed to list Gmail accounts for user {user_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch Gmail accounts.",
        }


async def list_team_gmail_accounts(team_id: str) -> Dict[str, Any]:
    """List all connected Gmail inboxes for a team. Never returns tokens."""
    normalized_team_id = team_id.strip()

    try:
        collection = get_collection(GMAIL_ACCOUNTS_COLLECTION)
        cursor = collection.find({
            "team_id": normalized_team_id,
            "status": {"$ne": "revoked"},
        })

        accounts = []
        async for account in cursor:
            accounts.append(_serialize_gmail_account_public(account))

        logger.info(f"Listed {len(accounts)} Gmail accounts for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Team Gmail accounts fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(accounts),
                "accounts": accounts,
            },
        }

    except Exception as e:
        logger.error(f"Failed to list Gmail accounts for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch team Gmail accounts.",
        }


async def disconnect_gmail_account(user_id: str, account_id: str) -> Dict[str, Any]:
    """Revoke Google token and mark a Gmail account as disconnected."""
    try:
        try:
            object_id = ObjectId(account_id.strip())
        except InvalidId:
            return {
                "success": False,
                "status_code": 400,
                "message": "Invalid account_id.",
            }

        collection = get_collection(GMAIL_ACCOUNTS_COLLECTION)
        account = await collection.find_one({"_id": object_id, "user_id": user_id})

        if not account:
            return {
                "success": False,
                "status_code": 404,
                "message": "Gmail account not found.",
            }

        refresh_token = account.get("refresh_token")
        if refresh_token:
            try:
                await _revoke_google_token(refresh_token)
            except Exception as revoke_error:
                logger.warning(f"Failed to revoke Google token for account {account_id}: {revoke_error}")

        now = datetime.now(timezone.utc)
        await collection.update_one(
            {"_id": object_id},
            {
                "$set": {
                    "status": "revoked",
                    "updated_at": now,
                }
            },
        )

        logger.info(f"Gmail account {account_id} disconnected for user {user_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Gmail account disconnected.",
            "data": {
                "account_id": account_id,
            },
        }

    except Exception as e:
        logger.error(f"Failed to disconnect Gmail account {account_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to disconnect Gmail account.",
        }
