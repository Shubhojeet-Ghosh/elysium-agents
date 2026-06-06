from fastapi import APIRouter

from config.email_user_models import (
    CreateEmailUserRequest,
    ListTeamUsersRequest,
    LoginEmailUserRequest,
)
from controllers.email_agent_controller_files.email_team_users_controllers import (
    list_team_users_controller,
)
from controllers.email_agent_controller_files.email_user_auth_controllers import (
    create_email_user_controller,
    login_email_user_controller,
)

email_login_router = APIRouter(
    prefix="/email-auth",
    tags=["Email Auth"],
)


@email_login_router.post("/v1/register")
async def register_email_user_route(request_data: CreateEmailUserRequest):
    """Create a user or update name/password/department when the email already exists."""
    return await create_email_user_controller(request_data)


@email_login_router.post("/v1/login")
async def login_email_user_route(request_data: LoginEmailUserRequest):
    """Login with email and password. Returns a JWT valid for 30 days."""
    return await login_email_user_controller(request_data)


@email_login_router.post("/v1/list-team-users")
async def list_team_users_route(request_data: ListTeamUsersRequest):
    """List all users for a team with department name and description."""
    return await list_team_users_controller(request_data)
