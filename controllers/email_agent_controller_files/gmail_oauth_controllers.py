from fastapi.responses import JSONResponse

from config.gmail_models import CreateGmailAccountRequest, ListTeamGmailAccountsRequest
from logging_config import get_logger
from services.email_agent_services.gmail_oauth_services import (
    create_gmail_account,
    disconnect_gmail_account,
    list_team_gmail_accounts,
)

logger = get_logger()


def _unauthorized_response(user_data: dict) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "success": False,
            "message": user_data.get("message", "Unauthorized"),
        },
    )


async def create_gmail_account_controller(
    request_data: CreateGmailAccountRequest,
    user_data: dict,
):
    try:
        if not user_data or user_data.get("success") is False:
            return _unauthorized_response(user_data)

        user_id = user_data.get("user_id")
        team_id = user_data.get("team_id")
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: user_id missing."},
            )
        if not team_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: team_id missing."},
            )

        result = await create_gmail_account(
            user_id=user_id,
            team_id=team_id,
            inbox_name=request_data.inbox_name,
            code=request_data.code,
        )

        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to create Gmail inbox."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "account": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_gmail_account_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while creating the Gmail inbox.",
            },
        )


async def list_gmail_accounts_controller(user_data: dict):
    try:
        if not user_data or user_data.get("success") is False:
            return _unauthorized_response(user_data)

        team_id = user_data.get("team_id")
        if not team_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: team_id missing."},
            )

        result = await list_team_gmail_accounts(team_id=team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch Gmail accounts."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "accounts": result["data"]["accounts"],
            },
        )

    except Exception as e:
        logger.error(f"Error in list_gmail_accounts_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching Gmail accounts.",
            },
        )


async def disconnect_gmail_account_controller(account_id: str, user_data: dict):
    try:
        if not user_data or user_data.get("success") is False:
            return _unauthorized_response(user_data)

        user_id = user_data.get("user_id")
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid token: user_id missing."},
            )

        result = await disconnect_gmail_account(user_id=user_id, account_id=account_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to disconnect Gmail account."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "account_id": result["data"]["account_id"],
            },
        )

    except Exception as e:
        logger.error(f"Error in disconnect_gmail_account_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while disconnecting the Gmail account.",
            },
        )


async def list_team_gmail_accounts_controller(request_data: ListTeamGmailAccountsRequest):
    try:
        result = await list_team_gmail_accounts(team_id=request_data.team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch team Gmail accounts."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "accounts": result["data"]["accounts"],
            },
        )

    except Exception as e:
        logger.error(f"Error in list_team_gmail_accounts_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching team Gmail accounts.",
            },
        )
