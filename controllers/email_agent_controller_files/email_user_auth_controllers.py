from fastapi.responses import JSONResponse

from config.email_user_models import CreateEmailUserRequest, LoginEmailUserRequest
from logging_config import get_logger
from middlewares.jwt_middleware import decode_jwt_token
from services.email_agent_services.email_user_auth_services import (
    create_email_user,
    login_email_user,
)

logger = get_logger()


async def create_email_user_controller(request_data: CreateEmailUserRequest):
    try:
        result = await create_email_user(
            name=request_data.name,
            email=request_data.email,
            password=request_data.password,
            team_id=request_data.team_id,
            department_id=request_data.department_id,
            role=request_data.role,
        )

        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to register user."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "user": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_email_user_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while registering the user.",
            },
        )


async def login_email_user_controller(request_data: LoginEmailUserRequest):
    try:
        result = await login_email_user(
            email=request_data.email,
            password=request_data.password,
        )

        status_code = result.get("status_code", 200 if result.get("success") else 401)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Invalid email or password."),
                },
            )

        token = result["data"]["token"]
        decoded_token = decode_jwt_token(token)

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "token": token,
                "user": {
                    "user_id": result["data"]["user_id"],
                    "name": result["data"]["name"],
                    "email": result["data"]["email"],
                    "team_id": result["data"]["team_id"],
                    "department_id": result["data"]["department_id"],
                    "department_name": result["data"]["department_name"],
                    "role": result["data"]["role"],
                },
                "decoded_token": decoded_token,
            },
        )

    except Exception as e:
        logger.error(f"Error in login_email_user_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while logging in.",
            },
        )
