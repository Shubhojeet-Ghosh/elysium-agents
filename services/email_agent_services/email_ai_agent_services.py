from datetime import datetime, timezone
from typing import Any, Dict, List

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.email_agent_services.email_knowledge.email_knowledge_mongo_services import (
    get_knowledge_by_id,
)
from services.email_agent_services.email_tool_definitions.email_tool_definitions_mongo_services import (
    get_tools_by_ids,
)
from services.email_agent_services.email_recipient_rules.email_recipient_rules_mongo_services import (
    get_recipient_rule_by_id,
)
from services.email_agent_services.email_routing_rules.email_routing_rules_mongo_services import (
    get_routing_rule_by_id,
)
from services.email_agent_services.gmail_oauth_services import (
    GMAIL_ACCOUNTS_COLLECTION,
    get_gmail_account_by_id,
)
from services.mongo_services import get_collection

logger = get_logger()

EMAIL_AI_AGENTS_COLLECTION = "email-ai-agents"

DEFAULT_REPLY_ACTION: Dict[str, Any] = {
    "mode": "draft",
    "auto_send_min_confidence": 0.8,
}


def _format_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_email_ai_agent_id_str(agent: Dict[str, Any]) -> str:
    return str(agent["_id"])


def normalize_reply_action(reply_action: Dict[str, Any] | None) -> Dict[str, Any]:
    """Normalize reply delivery settings with safe defaults."""
    if not reply_action:
        return dict(DEFAULT_REPLY_ACTION)

    mode = reply_action.get("mode", DEFAULT_REPLY_ACTION["mode"])
    if mode not in ("draft", "auto_send"):
        mode = DEFAULT_REPLY_ACTION["mode"]

    try:
        confidence = float(reply_action.get(
            "auto_send_min_confidence",
            DEFAULT_REPLY_ACTION["auto_send_min_confidence"],
        ))
    except (TypeError, ValueError):
        confidence = DEFAULT_REPLY_ACTION["auto_send_min_confidence"]

    confidence = max(0.0, min(1.0, confidence))

    return {
        "mode": mode,
        "auto_send_min_confidence": confidence,
    }


async def get_email_ai_agent_by_id(agent_id: str) -> Dict[str, Any] | None:
    """Fetch an email AI agent by MongoDB _id."""
    try:
        object_id = ObjectId(agent_id.strip())
    except InvalidId:
        return None

    collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
    return await collection.find_one({"_id": object_id})


def _serialize_email_ai_agent(agent: Dict[str, Any], gmail_account: Dict[str, Any] | None) -> Dict[str, Any]:
    return {
        "agent_id": get_email_ai_agent_id_str(agent),
        "name": agent.get("name", ""),
        "gmail_account_id": agent.get("gmail_account_id", ""),
        "user_id": agent.get("user_id", ""),
        "team_id": agent.get("team_id", ""),
        "status": agent.get("status", "active"),
        "activated_at": _format_datetime(agent.get("activated_at")),
        "sync_status": agent.get("sync_status", "idle"),
        "last_synced_at": _format_datetime(agent.get("last_synced_at")) if agent.get("last_synced_at") else None,
        "last_sync_error": agent.get("last_sync_error"),
        "inbox_name": gmail_account.get("inbox_name", "") if gmail_account else "",
        "email_address": gmail_account.get("email_address", "") if gmail_account else "",
        "system_prompt": agent.get("system_prompt", ""),
        "email_format_template": agent.get("email_format_template", "") or "",
        "knowledge_id": agent.get("knowledge_id", ""),
        "tool_ids": agent.get("tool_ids", []),
        "llm_model": agent.get("llm_model", ""),
        "reply_action": normalize_reply_action(agent.get("reply_action")),
        "routing_rule_ids": agent.get("routing_rule_ids", []),
        "recipient_rule_ids": agent.get("recipient_rule_ids", []),
        "flow_id": (agent.get("flow_id") or "").strip(),
        "created_at": _format_datetime(agent.get("created_at")),
        "updated_at": _format_datetime(agent.get("updated_at")),
    }


async def _fetch_gmail_account_for_agent(agent: Dict[str, Any]) -> Dict[str, Any] | None:
    gmail_collection = get_collection(GMAIL_ACCOUNTS_COLLECTION)
    try:
        gmail_object_id = ObjectId(agent.get("gmail_account_id", ""))
        return await gmail_collection.find_one({"_id": gmail_object_id})
    except InvalidId:
        return None


async def _validate_knowledge_for_team(knowledge_id: str, team_id: str) -> Dict[str, Any] | None:
    knowledge_doc = await get_knowledge_by_id(knowledge_id)
    if not knowledge_doc:
        return {
            "success": False,
            "status_code": 400,
            "message": "Invalid knowledge_id. Knowledge does not exist.",
        }
    if knowledge_doc.get("team_id") != team_id:
        return {
            "success": False,
            "status_code": 400,
            "message": "Knowledge does not belong to your team.",
        }
    return None


async def _validate_gmail_account_for_team(
    gmail_account_id: str,
    team_id: str,
) -> Dict[str, Any] | None:
    gmail_account = await get_gmail_account_by_id(gmail_account_id)
    if not gmail_account:
        return {
            "success": False,
            "status_code": 400,
            "message": "Invalid gmail_account_id. Gmail inbox does not exist.",
        }
    if gmail_account.get("status") == "revoked":
        return {
            "success": False,
            "status_code": 400,
            "message": "Gmail inbox is disconnected. Connect it before creating an agent.",
        }
    if gmail_account.get("team_id") != team_id:
        return {
            "success": False,
            "status_code": 400,
            "message": "Gmail inbox does not belong to your team.",
        }
    return None


async def _validate_tools_for_team(
    tool_ids: List[str],
    team_id: str,
    *,
    require_at_least_one: bool = True,
) -> Dict[str, Any] | None:
    if not tool_ids:
        if require_at_least_one:
            return {
                "success": False,
                "status_code": 400,
                "message": "At least one tool_id is required.",
            }
        return None

    tools_by_id = await get_tools_by_ids(tool_ids)
    missing_tool_ids = [tool_id for tool_id in tool_ids if tool_id not in tools_by_id]
    if missing_tool_ids:
        return {
            "success": False,
            "status_code": 400,
            "message": f"Invalid tool_id(s): {', '.join(missing_tool_ids)}",
        }

    for tool_id in tool_ids:
        tool_doc = tools_by_id[tool_id]
        if tool_doc.get("team_id") != team_id:
            return {
                "success": False,
                "status_code": 400,
                "message": f"Tool {tool_id} does not belong to your team.",
            }
        if tool_doc.get("status") != "active":
            return {
                "success": False,
                "status_code": 400,
                "message": f"Tool {tool_id} is not active.",
            }
    return None


def _normalize_id_list(ids: List[str]) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()

    for value in ids:
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        normalized.append(stripped)

    return normalized


def _normalize_tool_ids(tool_ids: List[str]) -> List[str]:
    return _normalize_id_list(tool_ids)


async def _validate_routing_rules_for_team(
    routing_rule_ids: List[str],
    team_id: str,
) -> Dict[str, Any] | None:
    normalized_rule_ids = _normalize_id_list(routing_rule_ids)
    if not normalized_rule_ids:
        return None

    for rule_id in normalized_rule_ids:
        rule = await get_routing_rule_by_id(rule_id)
        if not rule:
            return {
                "success": False,
                "status_code": 400,
                "message": f"Invalid routing_rule_id: {rule_id}",
            }
        if rule.get("team_id") != team_id:
            return {
                "success": False,
                "status_code": 400,
                "message": f"Routing rule {rule_id} does not belong to your team.",
            }
    return None


async def _validate_recipient_rules_for_team(
    recipient_rule_ids: List[str],
    team_id: str,
) -> Dict[str, Any] | None:
    normalized_rule_ids = _normalize_id_list(recipient_rule_ids)
    if not normalized_rule_ids:
        return None

    for rule_id in normalized_rule_ids:
        rule = await get_recipient_rule_by_id(rule_id)
        if not rule:
            return {
                "success": False,
                "status_code": 400,
                "message": f"Invalid recipient_rule_id: {rule_id}",
            }
        if rule.get("team_id") != team_id:
            return {
                "success": False,
                "status_code": 400,
                "message": f"Recipient rule {rule_id} does not belong to your team.",
            }
    return None


async def create_email_ai_agent(
    user_id: str,
    team_id: str,
    name: str,
    gmail_account_id: str,
    system_prompt: str,
    knowledge_id: str,
    tool_ids: List[str],
    llm_model: str,
    reply_action: Dict[str, Any] | None = None,
    routing_rule_ids: List[str] | None = None,
    recipient_rule_ids: List[str] | None = None,
    email_format_template: str = "",
    flow_id: str = "",
) -> Dict[str, Any]:
    """Create an email AI agent linked to a Gmail inbox, system prompt, knowledge base, tools, and LLM model."""
    normalized_name = name.strip()
    normalized_team_id = team_id.strip()
    normalized_gmail_account_id = gmail_account_id.strip()
    normalized_system_prompt = system_prompt.strip()
    normalized_email_format_template = email_format_template.strip()
    normalized_knowledge_id = knowledge_id.strip()
    normalized_tool_ids = _normalize_tool_ids(tool_ids)
    normalized_llm_model = llm_model.strip()
    normalized_reply_action = normalize_reply_action(reply_action)
    normalized_routing_rule_ids = _normalize_id_list(routing_rule_ids or [])
    normalized_recipient_rule_ids = _normalize_id_list(recipient_rule_ids or [])
    normalized_requested_flow_id = flow_id.strip()

    if not normalized_llm_model:
        return {
            "success": False,
            "status_code": 400,
            "message": "llm_model cannot be empty.",
        }

    try:
        validation_error = await _validate_knowledge_for_team(
            normalized_knowledge_id, normalized_team_id
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_gmail_account_for_team(
            normalized_gmail_account_id, normalized_team_id
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_tools_for_team(
            normalized_tool_ids,
            normalized_team_id,
            require_at_least_one=False,
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_routing_rules_for_team(
            normalized_routing_rule_ids, normalized_team_id
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_recipient_rules_for_team(
            normalized_recipient_rule_ids, normalized_team_id
        )
        if validation_error:
            return validation_error

        if normalized_requested_flow_id:
            from services.email_agent_services.email_flows.email_flow_mongo_services import (
                validate_flow_available_for_agent,
            )

            validation_error = await validate_flow_available_for_agent(
                normalized_requested_flow_id,
                normalized_team_id,
            )
            if validation_error:
                return validation_error

        gmail_account = await get_gmail_account_by_id(normalized_gmail_account_id)
        now = datetime.now(timezone.utc)
        collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)

        document = {
            "name": normalized_name,
            "gmail_account_id": normalized_gmail_account_id,
            "system_prompt": normalized_system_prompt,
            "email_format_template": normalized_email_format_template,
            "knowledge_id": normalized_knowledge_id,
            "tool_ids": normalized_tool_ids,
            "llm_model": normalized_llm_model,
            "reply_action": normalized_reply_action,
            "routing_rule_ids": normalized_routing_rule_ids,
            "recipient_rule_ids": normalized_recipient_rule_ids,
            "user_id": user_id,
            "team_id": normalized_team_id,
            "status": "active",
            "activated_at": now,
            "sync_status": "idle",
            "last_synced_at": None,
            "last_sync_error": None,
            "created_at": now,
            "updated_at": now,
        }

        result = await collection.insert_one(document)
        agent_id = str(result.inserted_id)
        agent_doc = {**document, "_id": result.inserted_id}

        try:
            from services.email_agent_services.email_flows.email_flow_mongo_services import (
                attach_flow_to_agent,
                ensure_and_sync_agent_flow,
            )

            if normalized_requested_flow_id:
                agent_doc = await attach_flow_to_agent(
                    agent_doc,
                    normalized_requested_flow_id,
                )
            else:
                linked_flow_id = await ensure_and_sync_agent_flow(agent_doc)
                agent_doc["flow_id"] = linked_flow_id
        except Exception as flow_error:
            await collection.delete_one({"_id": result.inserted_id})
            logger.error(
                f"Failed to create default workflow for agent {agent_id}: {flow_error}",
                exc_info=True,
            )
            return {
                "success": False,
                "status_code": 500,
                "message": "Email AI agent created but default workflow setup failed.",
            }

        logger.info(f"Created email AI agent {agent_id} for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 201,
            "message": "Email AI agent created successfully.",
            "data": _serialize_email_ai_agent(
                agent_doc,
                gmail_account,
            ),
        }

    except Exception as e:
        logger.error(f"Failed to create email AI agent for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create email AI agent.",
        }


async def get_email_ai_agent_detail(agent_id: str) -> Dict[str, Any]:
    """Fetch a single email AI agent by agent_id."""
    normalized_agent_id = agent_id.strip()

    try:
        agent = await get_email_ai_agent_by_id(normalized_agent_id)
        if not agent:
            return {
                "success": False,
                "status_code": 404,
                "message": "Email AI agent not found.",
            }

        gmail_account = await _fetch_gmail_account_for_agent(agent)

        return {
            "success": True,
            "status_code": 200,
            "message": "Email AI agent fetched successfully.",
            "data": _serialize_email_ai_agent(agent, gmail_account),
        }

    except Exception as e:
        logger.error(f"Failed to fetch email AI agent {normalized_agent_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch email AI agent.",
        }


async def update_email_ai_agent(
    team_id: str,
    agent_id: str,
    name: str,
    gmail_account_id: str,
    system_prompt: str,
    knowledge_id: str,
    tool_ids: List[str],
    llm_model: str,
    reply_action: Dict[str, Any] | None = None,
    routing_rule_ids: List[str] | None = None,
    recipient_rule_ids: List[str] | None = None,
    email_format_template: str = "",
    flow_id: str | None = None,
) -> Dict[str, Any]:
    """Update an existing email AI agent's configuration fields."""
    normalized_team_id = team_id.strip()
    normalized_agent_id = agent_id.strip()
    normalized_name = name.strip()
    normalized_gmail_account_id = gmail_account_id.strip()
    normalized_system_prompt = system_prompt.strip()
    normalized_email_format_template = email_format_template.strip()
    normalized_knowledge_id = knowledge_id.strip()
    normalized_tool_ids = _normalize_tool_ids(tool_ids)
    normalized_llm_model = llm_model.strip()
    normalized_reply_action = normalize_reply_action(reply_action)
    normalized_routing_rule_ids = _normalize_id_list(routing_rule_ids or [])
    normalized_recipient_rule_ids = _normalize_id_list(recipient_rule_ids or [])

    if not normalized_llm_model:
        return {
            "success": False,
            "status_code": 400,
            "message": "llm_model cannot be empty.",
        }

    try:
        agent = await get_email_ai_agent_by_id(normalized_agent_id)
        if not agent:
            return {
                "success": False,
                "status_code": 404,
                "message": "Email AI agent not found.",
            }

        if agent.get("team_id") != normalized_team_id:
            return {
                "success": False,
                "status_code": 403,
                "message": "Email AI agent does not belong to your team.",
            }

        current_flow_id = (agent.get("flow_id") or "").strip()

        if flow_id is not None:
            normalized_requested_flow_id = flow_id.strip()
            if normalized_requested_flow_id and normalized_requested_flow_id != current_flow_id:
                from services.email_agent_services.email_flows.email_flow_mongo_services import (
                    validate_flow_available_for_agent,
                )

                validation_error = await validate_flow_available_for_agent(
                    normalized_requested_flow_id,
                    normalized_team_id,
                    exclude_agent_id=normalized_agent_id,
                )
                if validation_error:
                    return validation_error

        validation_error = await _validate_knowledge_for_team(
            normalized_knowledge_id, normalized_team_id
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_gmail_account_for_team(
            normalized_gmail_account_id, normalized_team_id
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_tools_for_team(
            normalized_tool_ids,
            normalized_team_id,
            require_at_least_one=False,
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_routing_rules_for_team(
            normalized_routing_rule_ids, normalized_team_id
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_recipient_rules_for_team(
            normalized_recipient_rule_ids, normalized_team_id
        )
        if validation_error:
            return validation_error

        gmail_account = await get_gmail_account_by_id(normalized_gmail_account_id)
        collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
        now = datetime.now(timezone.utc)

        update_fields = {
            "name": normalized_name,
            "gmail_account_id": normalized_gmail_account_id,
            "system_prompt": normalized_system_prompt,
            "email_format_template": normalized_email_format_template,
            "knowledge_id": normalized_knowledge_id,
            "tool_ids": normalized_tool_ids,
            "llm_model": normalized_llm_model,
            "reply_action": normalized_reply_action,
            "routing_rule_ids": normalized_routing_rule_ids,
            "recipient_rule_ids": normalized_recipient_rule_ids,
            "updated_at": now,
        }

        if flow_id is not None:
            normalized_requested_flow_id = flow_id.strip()
            if normalized_requested_flow_id and normalized_requested_flow_id != current_flow_id:
                update_fields["flow_id"] = normalized_requested_flow_id

        await collection.update_one(
            {"_id": agent["_id"]},
            {"$set": update_fields},
        )

        updated_agent = {**agent, **update_fields}

        flow_synced = False
        try:
            from services.email_agent_services.email_flows.email_flow_mongo_services import (
                attach_flow_to_agent,
                ensure_and_sync_agent_flow,
                sync_flow_from_agent,
            )

            final_flow_id = (updated_agent.get("flow_id") or "").strip()
            requested_flow_id = flow_id.strip() if flow_id is not None else ""

            if flow_id is not None and requested_flow_id and requested_flow_id != current_flow_id:
                updated_agent = await attach_flow_to_agent(updated_agent, requested_flow_id)
                final_flow_id = updated_agent.get("flow_id", "")
            elif final_flow_id:
                await sync_flow_from_agent(final_flow_id, updated_agent)
                flow_synced = True
            else:
                final_flow_id = await ensure_and_sync_agent_flow(updated_agent)
                flow_synced = True

            updated_agent["flow_id"] = final_flow_id
        except Exception as flow_error:
            logger.error(
                f"Failed to sync default workflow for agent {normalized_agent_id}: {flow_error}",
                exc_info=True,
            )
            return {
                "success": False,
                "status_code": 500,
                "message": "Email AI agent updated but workflow sync failed.",
            }

        logger.info(f"Updated email AI agent {normalized_agent_id} for team {normalized_team_id}")

        agent_payload = _serialize_email_ai_agent(updated_agent, gmail_account)
        agent_payload["flow_synced"] = flow_synced

        return {
            "success": True,
            "status_code": 200,
            "message": "Email AI agent updated successfully.",
            "data": agent_payload,
        }

    except Exception as e:
        logger.error(
            f"Failed to update email AI agent {normalized_agent_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to update email AI agent.",
        }


async def list_team_email_ai_agents(team_id: str) -> Dict[str, Any]:
    """List all email AI agents for a team with linked inbox details."""
    normalized_team_id = team_id.strip()

    try:
        collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
        cursor = collection.find({"team_id": normalized_team_id})
        agents = []

        async for agent in cursor:
            gmail_account = await _fetch_gmail_account_for_agent(agent)
            agents.append(_serialize_email_ai_agent(agent, gmail_account))

        logger.info(f"Listed {len(agents)} email AI agents for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Email AI agents fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(agents),
                "agents": agents,
            },
        }

    except Exception as e:
        logger.error(f"Failed to list email AI agents for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch email AI agents.",
        }
