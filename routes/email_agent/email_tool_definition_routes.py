from fastapi import APIRouter

from config.email_tool_definition_models import (
    CreateEmailToolDefinitionRequest,
    DeleteEmailToolDefinitionRequest,
    ListTeamEmailToolDefinitionsRequest,
)
from controllers.email_agent_controller_files.email_tool_definition_controllers import (
    create_email_tool_definition_controller,
    delete_email_tool_definition_controller,
    list_team_email_tool_definitions_controller,
)

email_tool_definition_router = APIRouter(
    prefix="/email-tool-definitions",
    tags=["Email Tool Definitions"],
)


@email_tool_definition_router.post("/v1/create")
async def create_email_tool_definition_route(request_data: CreateEmailToolDefinitionRequest):
    """Register an external HTTP tool for LLM tool calling. Public — no JWT required."""
    return await create_email_tool_definition_controller(request_data)


@email_tool_definition_router.post("/v1/list-team-tools")
async def list_team_email_tool_definitions_route(
    request_data: ListTeamEmailToolDefinitionsRequest,
):
    """List all registered tools for a team."""
    return await list_team_email_tool_definitions_controller(request_data)


@email_tool_definition_router.post("/v1/delete")
async def delete_email_tool_definition_route(request_data: DeleteEmailToolDefinitionRequest):
    """Delete a tool by tool_id (MongoDB _id)."""
    return await delete_email_tool_definition_controller(request_data)
