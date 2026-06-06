from fastapi.responses import JSONResponse

from config.email_department_models import (
    CreateDepartmentRequest,
    ListTeamDepartmentsRequest,
)
from logging_config import get_logger
from services.email_agent_services.email_department_services import (
    create_department,
    list_team_departments,
)

logger = get_logger()


async def create_department_controller(request_data: CreateDepartmentRequest):
    try:
        result = await create_department(
            name=request_data.name,
            description=request_data.description,
            team_id=request_data.team_id,
        )

        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to create department."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "department": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_department_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while creating the department.",
            },
        )


async def list_team_departments_controller(request_data: ListTeamDepartmentsRequest):
    try:
        result = await list_team_departments(team_id=request_data.team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch team departments."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "departments": result["data"]["departments"],
            },
        )

    except Exception as e:
        logger.error(f"Error in list_team_departments_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching team departments.",
            },
        )
