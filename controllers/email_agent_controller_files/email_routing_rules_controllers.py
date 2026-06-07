from fastapi.responses import JSONResponse

from config.email_routing_rules_models import (
    CreateEmailRoutingRuleRequest,
    DeleteEmailRoutingRuleRequest,
    ListTeamEmailRoutingRulesRequest,
    UpdateEmailRoutingRuleRequest,
)
from logging_config import get_logger
from services.email_agent_services.email_routing_rules.email_routing_rules_services import (
    create_email_routing_rule,
    delete_email_routing_rule,
    list_team_email_routing_rules,
    update_email_routing_rule,
)

logger = get_logger()


async def create_email_routing_rule_controller(request_data: CreateEmailRoutingRuleRequest):
    try:
        result = await create_email_routing_rule(
            team_id=request_data.team_id,
            department_id=request_data.department_id,
            rule_name=request_data.rule_name,
            routing_prompt=request_data.routing_prompt,
            priority=request_data.priority,
            is_fallback=request_data.is_fallback,
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to create routing rule."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "rule": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_email_routing_rule_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while creating the routing rule.",
            },
        )


async def update_email_routing_rule_controller(request_data: UpdateEmailRoutingRuleRequest):
    try:
        result = await update_email_routing_rule(
            routing_rule_id=request_data.routing_rule_id,
            team_id=request_data.team_id,
            department_id=request_data.department_id,
            rule_name=request_data.rule_name,
            routing_prompt=request_data.routing_prompt,
            priority=request_data.priority,
            is_fallback=request_data.is_fallback,
            status=request_data.status,
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to update routing rule."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "rule": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in update_email_routing_rule_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while updating the routing rule.",
            },
        )


async def list_team_email_routing_rules_controller(
    request_data: ListTeamEmailRoutingRulesRequest,
):
    try:
        result = await list_team_email_routing_rules(
            team_id=request_data.team_id,
            include_inactive=request_data.include_inactive,
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch routing rules."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "rules": result["data"]["rules"],
            },
        )

    except Exception as e:
        logger.error(f"Error in list_team_email_routing_rules_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching routing rules.",
            },
        )


async def delete_email_routing_rule_controller(request_data: DeleteEmailRoutingRuleRequest):
    try:
        result = await delete_email_routing_rule(routing_rule_id=request_data.routing_rule_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to delete routing rule."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "rule": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in delete_email_routing_rule_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while deleting the routing rule.",
            },
        )
