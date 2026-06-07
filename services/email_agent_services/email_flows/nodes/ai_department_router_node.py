from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_department_router_llm_services import (
    route_department_with_llm,
    summarize_routing_rules,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_LOG_STATUS_SKIPPED,
    NODE_TYPE_AI_DEPARTMENT_ROUTER,
)
from services.email_agent_services.email_flows.email_flow_thread_data_services import (
    update_thread_department_id,
)
from services.email_agent_services.email_routing_rules.email_routing_rules_mongo_services import (
    get_routing_rule_id_str,
    get_routing_rules_by_ids,
)

logger = get_logger()

NODE_ID = "ai_department_router"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_routing_rule_ids(agent: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    config_ids = config.get("routing_rule_ids") or []
    if config_ids:
        return [str(rule_id).strip() for rule_id in config_ids if str(rule_id).strip()]

    agent_ids = agent.get("routing_rule_ids") or []
    return [str(rule_id).strip() for rule_id in agent_ids if str(rule_id).strip()]


async def _load_active_routing_rules(
    *,
    routing_rule_ids: List[str],
    team_id: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    rules_map = await get_routing_rules_by_ids(routing_rule_ids)

    active_rules: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for rule_id in routing_rule_ids:
        rule = rules_map.get(rule_id)
        if not rule:
            warnings.append(f"Routing rule id '{rule_id}' not found.")
            continue
        if (rule.get("status") or "").strip().lower() != "active":
            warnings.append(
                f"Routing rule '{rule.get('rule_name', rule_id)}' is not active."
            )
            continue
        if (rule.get("team_id") or "").strip() != team_id.strip():
            warnings.append(
                f"Routing rule '{rule.get('rule_name', rule_id)}' does not belong to team."
            )
            continue
        active_rules.append(rule)

    # All active agent rules go to the LLM — is_fallback does not exclude a rule from matching.
    llm_rules = sorted(
        active_rules,
        key=lambda rule: (int(rule.get("priority", 100)), get_routing_rule_id_str(rule)),
    )

    fallback_rules = [rule for rule in active_rules if bool(rule.get("is_fallback"))]
    fallback_rule = None
    if fallback_rules:
        fallback_rule = sorted(
            fallback_rules,
            key=lambda rule: (int(rule.get("priority", 100)), get_routing_rule_id_str(rule)),
        )[0]

    return active_rules, llm_rules, fallback_rule, warnings


def _set_routing_context_defaults(context: Dict[str, Any]) -> None:
    context["routing"] = {
        "department_id": "",
        "routing_rule_id": "",
        "rule_name": "",
        "decision_source": "",
        "reason": "",
    }


def _apply_routing_result(context: Dict[str, Any], routing_result: Dict[str, Any]) -> None:
    department_id = (routing_result.get("department_id") or "").strip()
    context["routing"] = {
        "department_id": department_id,
        "routing_rule_id": routing_result.get("routing_rule_id", "") or "",
        "rule_name": routing_result.get("rule_name", "") or "",
        "decision_source": routing_result.get("decision_source", "") or "",
        "reason": routing_result.get("reason", "") or "",
    }
    thread = context.get("thread")
    if isinstance(thread, dict):
        thread["department_id"] = department_id


async def execute_ai_department_router_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Route the thread to a department using agent routing rules + LLM.

    Writes context.routing and updates email-threads.department_id when matched.
    """
    started_at = _utc_now()
    routing_rule_ids = _resolve_routing_rule_ids(agent, config)
    team_id = (context.get("team_id") or agent.get("team_id") or "").strip()
    thread_id = (context.get("thread_id") or "").strip()
    gmail_account_id = (agent.get("gmail_account_id") or "").strip()
    llm_model = (agent.get("llm_model") or "").strip()

    input_summary = {
        "routing_rule_ids": routing_rule_ids,
        "routing_rule_count": len(routing_rule_ids),
        "llm_model": llm_model,
        "thread_message_count": len((context.get("thread") or {}).get("messages") or []),
    }

    logger.info(
        f"ai_department_router_node started thread_id={thread_id} "
        f"routing_rule_ids={routing_rule_ids}"
    )

    try:
        if not routing_rule_ids:
            _set_routing_context_defaults(context)
            logger.info(
                f"ai_department_router_node skipped thread_id={thread_id} — "
                "no routing_rule_ids configured"
            )
            completed_at = _utc_now()
            node_log = {
                "node_id": NODE_ID,
                "node_type": NODE_TYPE_AI_DEPARTMENT_ROUTER,
                "status": NODE_LOG_STATUS_SKIPPED,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
                "input_summary": input_summary,
                "output": {
                    "routing_rules_registered": False,
                    "configured_routing_rule_ids": [],
                    "registered_routing_rules": [],
                    "llm_decision": "skipped",
                    "skip_reason": "No routing_rule_ids on agent or node config.",
                    "routing": context["routing"],
                    "context": context,
                },
                "error": None,
            }
            return context, node_log

        active_rules, llm_rules, fallback_rule, load_warnings = await _load_active_routing_rules(
            routing_rule_ids=routing_rule_ids,
            team_id=team_id,
        )
        registered_rules = summarize_routing_rules(active_rules)

        if not active_rules:
            _set_routing_context_defaults(context)
            logger.warning(
                f"ai_department_router_node skipped thread_id={thread_id} — "
                f"no active routing rules resolved. warnings={load_warnings}"
            )
            completed_at = _utc_now()
            node_log = {
                "node_id": NODE_ID,
                "node_type": NODE_TYPE_AI_DEPARTMENT_ROUTER,
                "status": NODE_LOG_STATUS_SKIPPED,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
                "input_summary": input_summary,
                "output": {
                    "routing_rules_registered": True,
                    "configured_routing_rule_ids": routing_rule_ids,
                    "registered_routing_rules": [],
                    "llm_decision": "skipped",
                    "skip_reason": "No active routing rules resolved for configured routing_rule_ids.",
                    "warnings": load_warnings,
                    "routing": context["routing"],
                    "context": context,
                },
                "error": None,
            }
            return context, node_log

        logger.info(
            f"ai_department_router_node loaded {len(active_rules)} active rule(s) "
            f"({len(llm_rules)} for LLM, fallback={'yes' if fallback_rule else 'no'}) "
            f"thread_id={thread_id}"
        )

        routing_result = await route_department_with_llm(
            context=context,
            llm_rules=llm_rules,
            fallback_rule=fallback_rule,
            llm_model=llm_model,
        )
        _apply_routing_result(context, routing_result)

        department_id = (routing_result.get("department_id") or "").strip()
        decision_source = routing_result.get("decision_source", "")

        thread_updated = False
        if department_id:
            thread_updated = await update_thread_department_id(
                thread_id=thread_id,
                team_id=team_id,
                gmail_account_id=gmail_account_id,
                department_id=department_id,
            )
            logger.info(
                f"ai_department_router_node routed thread_id={thread_id} "
                f"department_id={department_id} decision_source={decision_source} "
                f"thread_updated={thread_updated}"
            )
        else:
            logger.info(
                f"ai_department_router_node left department empty for thread_id={thread_id} "
                f"decision_source={decision_source}"
            )

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_AI_DEPARTMENT_ROUTER,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "routing_rules_registered": True,
                "configured_routing_rule_ids": routing_rule_ids,
                "registered_routing_rules": registered_rules,
                "llm_rules_sent_to_model": summarize_routing_rules(llm_rules),
                "fallback_rule": (
                    summarize_routing_rules([fallback_rule])[0]
                    if fallback_rule else None
                ),
                "llm_decision": decision_source,
                "llm_model": routing_result.get("llm_model", ""),
                "llm_attempts": routing_result.get("attempts", 0),
                "routing": context["routing"],
                "thread_department_updated": thread_updated,
                "warnings": load_warnings,
                "llm_raw_response_preview": (routing_result.get("llm_raw_response") or "")[:500],
                "context": context,
                "downstream_hints": {
                    "ai_recipients_generator": {
                        "uses": ["thread", "routing"],
                    },
                    "generate_email": {
                        "uses": ["thread", "routing", "kb_chunks", "tool_results"],
                    },
                },
            },
            "error": None,
        }
        return context, node_log

    except Exception as exc:
        logger.error(
            f"ai_department_router_node failed thread_id={thread_id} "
            f"routing_rule_ids={routing_rule_ids}: {exc}",
            exc_info=True,
        )
        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        context.setdefault("errors", []).append({
            "node_id": NODE_ID,
            "message": str(exc),
        })

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_AI_DEPARTMENT_ROUTER,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
