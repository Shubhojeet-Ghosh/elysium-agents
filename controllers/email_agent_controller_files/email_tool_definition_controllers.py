from fastapi.responses import JSONResponse

from config.email_tool_definition_models import (
    CreateEmailToolDefinitionRequest,
    DeleteEmailToolDefinitionRequest,
    ListTeamEmailToolDefinitionsRequest,
)
from logging_config import get_logger
from services.email_agent_services.email_tool_definitions.email_tool_definitions_services import (
    create_email_tool_definition,
    delete_email_tool_definition,
    list_team_email_tool_definitions,
)

logger = get_logger()


async def create_email_tool_definition_controller(
    request_data: CreateEmailToolDefinitionRequest,
):
    try:
        result = await create_email_tool_definition(
            team_id=request_data.team_id,
            name=request_data.name,
            display_name=request_data.display_name,
            description=request_data.description,
            endpoint_url=request_data.endpoint_url,
            http_method=request_data.http_method,
            inputs=request_data.inputs,
        )

        status_code = result.get("status_code", 201 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to create tool."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "tool": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_email_tool_definition_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while creating the tool.",
            },
        )


async def list_team_email_tool_definitions_controller(
    request_data: ListTeamEmailToolDefinitionsRequest,
):
    try:
        result = await list_team_email_tool_definitions(team_id=request_data.team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch team tools."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "tools": result["data"]["tools"],
            },
        )

    except Exception as e:
        logger.error(
            f"Error in list_team_email_tool_definitions_controller: {e}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching team tools.",
            },
        )


async def delete_email_tool_definition_controller(
    request_data: DeleteEmailToolDefinitionRequest,
):
    try:
        result = await delete_email_tool_definition(tool_id=request_data.tool_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to delete tool."),
                },
            )

        data = result.get("data", {})
        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "tool_id": data.get("tool_id"),
                "team_id": data.get("team_id"),
                "name": data.get("name"),
            },
        )

    except Exception as e:
        logger.error(f"Error in delete_email_tool_definition_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while deleting the tool.",
            },
        )
