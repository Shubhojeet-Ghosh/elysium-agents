from fastapi import APIRouter

from config.email_department_models import (
    CreateDepartmentRequest,
    ListTeamDepartmentsRequest,
)
from controllers.email_agent_controller_files.email_department_controllers import (
    create_department_controller,
    list_team_departments_controller,
)

email_department_router = APIRouter(
    prefix="/email-departments",
    tags=["Email Departments"],
)


@email_department_router.post("/v1/create")
async def create_department_route(request_data: CreateDepartmentRequest):
    """Create a department with name and description for a team."""
    return await create_department_controller(request_data)


@email_department_router.post("/v1/list-team-departments")
async def list_team_departments_route(request_data: ListTeamDepartmentsRequest):
    """List all departments for a team. Public — no JWT required."""
    return await list_team_departments_controller(request_data)
