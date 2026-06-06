from fastapi import APIRouter, Depends

from config.gmail_models import CreateGmailAccountRequest, ListTeamGmailAccountsRequest
from controllers.email_agent_controller_files.gmail_oauth_controllers import (
    create_gmail_account_controller,
    disconnect_gmail_account_controller,
    list_gmail_accounts_controller,
    list_team_gmail_accounts_controller,
)
from middlewares.jwt_middleware import authorize_user

gmail_router = APIRouter(
    prefix="/email/gmail",
    tags=["Gmail OAuth"],
)


@gmail_router.post("/v1/accounts")
async def create_gmail_account_route(
    request_data: CreateGmailAccountRequest,
    user: dict = Depends(authorize_user),
):
    """Create a Gmail inbox account from a Google OAuth authorization code."""
    return await create_gmail_account_controller(request_data, user)


@gmail_router.get("/v1/accounts")
async def list_gmail_accounts_route(user: dict = Depends(authorize_user)):
    """List all Gmail inbox accounts for the logged-in user's team (admin and member)."""
    return await list_gmail_accounts_controller(user)


@gmail_router.post("/v1/list-team-accounts")
async def list_team_gmail_accounts_route(request_data: ListTeamGmailAccountsRequest):
    """List all connected Gmail inboxes for a team."""
    return await list_team_gmail_accounts_controller(request_data)


@gmail_router.delete("/v1/accounts/{account_id}")
async def disconnect_gmail_account_route(
    account_id: str,
    user: dict = Depends(authorize_user),
):
    """Disconnect a Gmail inbox account."""
    return await disconnect_gmail_account_controller(account_id, user)
