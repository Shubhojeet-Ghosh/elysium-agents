from fastapi import APIRouter

from config.email_routing_rules_models import (
    CreateEmailRoutingRuleRequest,
    DeleteEmailRoutingRuleRequest,
    ListTeamEmailRoutingRulesRequest,
    UpdateEmailRoutingRuleRequest,
)
from controllers.email_agent_controller_files.email_routing_rules_controllers import (
    create_email_routing_rule_controller,
    delete_email_routing_rule_controller,
    list_team_email_routing_rules_controller,
    update_email_routing_rule_controller,
)

email_routing_rules_router = APIRouter(
    prefix="/email-routing-rules",
    tags=["Email Routing Rules"],
)


@email_routing_rules_router.post("/v1/create")
async def create_email_routing_rule_route(request_data: CreateEmailRoutingRuleRequest):
    """Create a team routing rule: department + natural-language condition for the LLM router."""
    return await create_email_routing_rule_controller(request_data)


@email_routing_rules_router.post("/v1/update")
async def update_email_routing_rule_route(request_data: UpdateEmailRoutingRuleRequest):
    """Update a routing rule's department, prompt, priority, fallback flag, or status."""
    return await update_email_routing_rule_controller(request_data)


@email_routing_rules_router.post("/v1/list-team-rules")
async def list_team_email_routing_rules_route(
    request_data: ListTeamEmailRoutingRulesRequest,
):
    """List routing rules for a team (active only by default)."""
    return await list_team_email_routing_rules_controller(request_data)


@email_routing_rules_router.post("/v1/delete")
async def delete_email_routing_rule_route(request_data: DeleteEmailRoutingRuleRequest):
    """Delete a routing rule by routing_rule_id."""
    return await delete_email_routing_rule_controller(request_data)
