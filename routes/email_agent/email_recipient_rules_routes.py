from fastapi import APIRouter

from config.email_recipient_rules_models import (
    CreateEmailRecipientRuleRequest,
    ListTeamEmailRecipientRulesRequest,
    UpdateEmailRecipientRuleRequest,
)
from controllers.email_agent_controller_files.email_recipient_rules_controllers import (
    create_email_recipient_rule_controller,
    list_team_email_recipient_rules_controller,
    update_email_recipient_rule_controller,
)

email_recipient_rules_router = APIRouter(
    prefix="/email-recipient-rules",
    tags=["Email Recipient Rules"],
)


@email_recipient_rules_router.post("/v1/create")
async def create_email_recipient_rule_route(request_data: CreateEmailRecipientRuleRequest):
    """Create a team recipient rule: NL condition + CC/BCC user_ids."""
    return await create_email_recipient_rule_controller(request_data)


@email_recipient_rules_router.post("/v1/update")
async def update_email_recipient_rule_route(request_data: UpdateEmailRecipientRuleRequest):
    """Update a recipient rule's prompt and CC/BCC user lists."""
    return await update_email_recipient_rule_controller(request_data)


@email_recipient_rules_router.post("/v1/list-team-rules")
async def list_team_email_recipient_rules_route(
    request_data: ListTeamEmailRecipientRulesRequest,
):
    """List all recipient rules for a team."""
    return await list_team_email_recipient_rules_controller(request_data)
