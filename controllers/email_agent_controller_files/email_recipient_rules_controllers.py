from fastapi.responses import JSONResponse

from config.email_recipient_rules_models import (
    CreateEmailRecipientRuleRequest,
    ListTeamEmailRecipientRulesRequest,
    UpdateEmailRecipientRuleRequest,
)
from logging_config import get_logger
from services.email_agent_services.email_recipient_rules.email_recipient_rules_services import (
    create_email_recipient_rule,
    list_team_email_recipient_rules,
    update_email_recipient_rule,
)

logger = get_logger()


async def create_email_recipient_rule_controller(request_data: CreateEmailRecipientRuleRequest):
    try:
        result = await create_email_recipient_rule(
            team_id=request_data.team_id,
            rule_name=request_data.rule_name,
            recipient_prompt=request_data.recipient_prompt,
            cc_user_ids=request_data.cc_user_ids,
            bcc_user_ids=request_data.bcc_user_ids,
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to create recipient rule."),
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
        logger.error(f"Error in create_email_recipient_rule_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while creating the recipient rule.",
            },
        )


async def update_email_recipient_rule_controller(request_data: UpdateEmailRecipientRuleRequest):
    try:
        result = await update_email_recipient_rule(
            recipient_rule_id=request_data.recipient_rule_id,
            team_id=request_data.team_id,
            rule_name=request_data.rule_name,
            recipient_prompt=request_data.recipient_prompt,
            cc_user_ids=request_data.cc_user_ids,
            bcc_user_ids=request_data.bcc_user_ids,
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to update recipient rule."),
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
        logger.error(f"Error in update_email_recipient_rule_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while updating the recipient rule.",
            },
        )


async def list_team_email_recipient_rules_controller(
    request_data: ListTeamEmailRecipientRulesRequest,
):
    try:
        result = await list_team_email_recipient_rules(team_id=request_data.team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch recipient rules."),
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
        logger.error(f"Error in list_team_email_recipient_rules_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching recipient rules.",
            },
        )
