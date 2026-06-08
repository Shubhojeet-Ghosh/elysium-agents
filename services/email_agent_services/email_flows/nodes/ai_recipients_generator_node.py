from datetime import datetime, timezone
from typing import Any, Dict, List, Set, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_LOG_STATUS_SKIPPED,
    NODE_TYPE_AI_RECIPIENTS_GENERATOR,
)
from services.email_agent_services.email_flows.email_gmail_reply_services import (
    apply_base_reply_recipients,
)
from services.email_agent_services.email_flows.email_recipient_rules_llm_services import (
    evaluate_recipient_rules_with_llm,
    summarize_recipient_rules_for_llm,
)
from services.email_agent_services.email_recipient_rules.email_recipient_rules_mongo_services import (
    get_recipient_rule_id_str,
    get_recipient_rules_by_ids,
)
from services.email_agent_services.email_user_auth_services import (
    get_email_users_by_ids,
)

logger = get_logger()

NODE_ID = "ai_recipients_generator"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_recipient_rule_ids(agent: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    config_ids = config.get("recipient_rule_ids") or []
    if config_ids:
        return [str(rule_id).strip() for rule_id in config_ids if str(rule_id).strip()]

    agent_ids = agent.get("recipient_rule_ids") or []
    return [str(rule_id).strip() for rule_id in agent_ids if str(rule_id).strip()]


async def _load_recipient_rules(
    *,
    recipient_rule_ids: List[str],
    team_id: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    rules_map = await get_recipient_rules_by_ids(recipient_rule_ids)

    active_rules: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for rule_id in recipient_rule_ids:
        rule = rules_map.get(rule_id)
        if not rule:
            warnings.append(f"Recipient rule id '{rule_id}' not found.")
            continue
        if (rule.get("team_id") or "").strip() != team_id.strip():
            warnings.append(
                f"Recipient rule '{rule.get('rule_name', rule_id)}' does not belong to team."
            )
            continue
        active_rules.append(rule)

    return active_rules, warnings


def _apply_inbound_preserving_recipients(
    context: Dict[str, Any],
    *,
    rule_cc: List[str] | None = None,
    rule_bcc: List[str] | None = None,
    decision_source: str = "",
    reason: str = "",
    cc_user_ids: List[str] | None = None,
    bcc_user_ids: List[str] | None = None,
    cc_users: List[Dict[str, str]] | None = None,
    bcc_users: List[Dict[str, str]] | None = None,
    matched_rule_ids: List[str] | None = None,
    matched_recipient_rules: List[Dict[str, Any]] | None = None,
) -> Dict[str, List[str]]:
    resolved = apply_base_reply_recipients(
        context,
        rule_cc=rule_cc,
        rule_bcc=rule_bcc,
    )
    _apply_recipients_result(
        context,
        to_addresses=resolved["to"],
        cc_user_ids=cc_user_ids or [],
        bcc_user_ids=bcc_user_ids or [],
        cc_users=cc_users or [],
        bcc_users=bcc_users or [],
        cc_addresses=resolved["cc"],
        bcc_addresses=resolved["bcc"],
        matched_rule_ids=matched_rule_ids or [],
        matched_recipient_rules=matched_recipient_rules or [],
        decision_source=decision_source,
        reason=reason,
    )
    return resolved


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    deduped: List[str] = []
    for value in values:
        normalized = (value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _merge_recipient_user_ids(
    *,
    matched_rule_ids: List[str],
    rules_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    cc_user_ids: List[str] = []
    bcc_user_ids: List[str] = []

    for rule_id in matched_rule_ids:
        rule = rules_by_id.get(rule_id)
        if not rule:
            continue
        cc_user_ids.extend(rule.get("cc_user_ids") or [])
        bcc_user_ids.extend(rule.get("bcc_user_ids") or [])

    return _dedupe_preserve_order(cc_user_ids), _dedupe_preserve_order(bcc_user_ids)


async def _resolve_user_email_mappings(
    user_ids: List[str],
) -> Tuple[List[Dict[str, str]], List[str], List[str]]:
    """Map email-users _id -> email after matched rules are resolved."""
    if not user_ids:
        return [], [], []

    users_map = await get_email_users_by_ids(user_ids)
    user_mappings: List[Dict[str, str]] = []
    emails: List[str] = []
    warnings: List[str] = []
    seen_user_ids: Set[str] = set()

    for user_id in user_ids:
        if user_id in seen_user_ids:
            continue

        user = users_map.get(user_id)
        if not user:
            warnings.append(f"Recipient user id '{user_id}' not found.")
            seen_user_ids.add(user_id)
            continue

        email = (user.get("email") or "").strip()
        if not email:
            warnings.append(f"Recipient user id '{user_id}' has no email.")
            seen_user_ids.add(user_id)
            continue

        seen_user_ids.add(user_id)
        user_mappings.append({
            "user_id": user_id,
            "email": email,
            "name": (user.get("name") or "").strip(),
        })
        emails.append(email)

    return user_mappings, emails, warnings


def _map_user_ids_to_users(
    user_ids: List[str],
    users_by_id: Dict[str, Dict[str, str]],
) -> Tuple[List[Dict[str, str]], List[str]]:
    mapped_users: List[Dict[str, str]] = []
    emails: List[str] = []
    seen_user_ids: Set[str] = set()

    for user_id in user_ids:
        if user_id in seen_user_ids:
            continue
        user = users_by_id.get(user_id)
        if not user:
            continue
        seen_user_ids.add(user_id)
        mapped_users.append(user)
        emails.append(user["email"])

    return mapped_users, emails


def _build_users_by_id_lookup(
    user_mappings: List[Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    return {
        (user.get("user_id") or "").strip(): user
        for user in user_mappings
        if (user.get("user_id") or "").strip()
    }


def _build_matched_recipient_rules(
    *,
    matched_rule_ids: List[str],
    rules_by_id: Dict[str, Dict[str, Any]],
    users_by_id: Dict[str, Dict[str, str]],
) -> List[Dict[str, Any]]:
    matched_rules: List[Dict[str, Any]] = []

    for rule_id in matched_rule_ids:
        rule = rules_by_id.get(rule_id)
        if not rule:
            continue

        rule_cc_user_ids = _dedupe_preserve_order(rule.get("cc_user_ids") or [])
        rule_bcc_user_ids = _dedupe_preserve_order(rule.get("bcc_user_ids") or [])
        rule_cc_users, rule_cc_emails = _map_user_ids_to_users(rule_cc_user_ids, users_by_id)
        rule_bcc_users, rule_bcc_emails = _map_user_ids_to_users(rule_bcc_user_ids, users_by_id)

        matched_rules.append({
            "_id": rule_id,
            "rule_name": (rule.get("rule_name") or "").strip(),
            "cc_user_ids": rule_cc_user_ids,
            "bcc_user_ids": rule_bcc_user_ids,
            "cc_users": rule_cc_users,
            "bcc_users": rule_bcc_users,
            "cc": rule_cc_emails,
            "bcc": rule_bcc_emails,
        })

    return matched_rules


def _apply_recipients_result(
    context: Dict[str, Any],
    *,
    to_addresses: List[str],
    cc_user_ids: List[str],
    bcc_user_ids: List[str],
    cc_users: List[Dict[str, str]],
    bcc_users: List[Dict[str, str]],
    cc_addresses: List[str],
    bcc_addresses: List[str],
    matched_rule_ids: List[str],
    matched_recipient_rules: List[Dict[str, Any]],
    decision_source: str,
    reason: str,
) -> None:
    context["recipients"] = {
        "to": to_addresses,
        "cc": cc_addresses,
        "bcc": bcc_addresses,
        "cc_user_ids": cc_user_ids,
        "bcc_user_ids": bcc_user_ids,
        "cc_users": cc_users,
        "bcc_users": bcc_users,
        "matched_rule_ids": matched_rule_ids,
        "matched_recipient_rules": matched_recipient_rules,
        "decision_source": decision_source,
        "reason": reason,
    }


async def execute_ai_recipients_generator_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Evaluate agent recipient rules with LLM and build To/CC/BCC for the outgoing reply.

    Writes context.recipients.
    """
    started_at = _utc_now()
    recipient_rule_ids = _resolve_recipient_rule_ids(agent, config)
    team_id = (context.get("team_id") or agent.get("team_id") or "").strip()
    thread_id = (context.get("thread_id") or "").strip()
    llm_model = (agent.get("llm_model") or "").strip()

    input_summary = {
        "recipient_rule_ids": recipient_rule_ids,
        "recipient_rule_count": len(recipient_rule_ids),
        "llm_model": llm_model,
        "thread_message_count": len((context.get("thread") or {}).get("messages") or []),
    }

    logger.info(
        f"ai_recipients_generator_node started thread_id={thread_id} "
        f"recipient_rule_ids={recipient_rule_ids}"
    )

    try:
        if not recipient_rule_ids:
            _apply_inbound_preserving_recipients(
                context,
                decision_source="skipped",
                reason="No recipient_rule_ids on agent or node config.",
            )
            logger.info(
                f"ai_recipients_generator_node skipped thread_id={thread_id} — "
                "no recipient_rule_ids configured"
            )
            completed_at = _utc_now()
            node_log = {
                "node_id": NODE_ID,
                "node_type": NODE_TYPE_AI_RECIPIENTS_GENERATOR,
                "status": NODE_LOG_STATUS_SKIPPED,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
                "input_summary": input_summary,
                "output": {
                    "recipient_rules_registered": False,
                    "configured_recipient_rule_ids": [],
                    "registered_recipient_rules": [],
                    "llm_decision": "skipped",
                    "skip_reason": "No recipient_rule_ids on agent or node config.",
                    "recipients": context["recipients"],
                    "context": context,
                },
                "error": None,
            }
            return context, node_log

        active_rules, load_warnings = await _load_recipient_rules(
            recipient_rule_ids=recipient_rule_ids,
            team_id=team_id,
        )
        registered_rules = summarize_recipient_rules_for_llm(active_rules)
        rules_by_id = {
            get_recipient_rule_id_str(rule): rule
            for rule in active_rules
        }

        if not active_rules:
            _apply_inbound_preserving_recipients(
                context,
                decision_source="skipped",
                reason=(
                    "No active recipient rules resolved for configured recipient_rule_ids."
                ),
            )
            logger.warning(
                f"ai_recipients_generator_node skipped thread_id={thread_id} — "
                f"no active recipient rules resolved. warnings={load_warnings}"
            )
            completed_at = _utc_now()
            node_log = {
                "node_id": NODE_ID,
                "node_type": NODE_TYPE_AI_RECIPIENTS_GENERATOR,
                "status": NODE_LOG_STATUS_SKIPPED,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
                "input_summary": input_summary,
                "output": {
                    "recipient_rules_registered": True,
                    "configured_recipient_rule_ids": recipient_rule_ids,
                    "registered_recipient_rules": [],
                    "llm_decision": "skipped",
                    "skip_reason": (
                        "No active recipient rules resolved for configured recipient_rule_ids."
                    ),
                    "warnings": load_warnings,
                    "recipients": context["recipients"],
                    "context": context,
                },
                "error": None,
            }
            return context, node_log

        logger.info(
            f"ai_recipients_generator_node loaded {len(active_rules)} active rule(s) "
            f"thread_id={thread_id}"
        )

        llm_result = await evaluate_recipient_rules_with_llm(
            context=context,
            llm_rules=active_rules,
            llm_model=llm_model,
        )

        matched_rules = llm_result.get("matched_rules") or []
        matched_rule_ids = [
            match["_id"]
            for match in matched_rules
            if isinstance(match, dict) and (match.get("_id") or "").strip()
        ]
        decision_source = llm_result.get("decision_source", "") or ""

        cc_user_ids: List[str] = []
        bcc_user_ids: List[str] = []
        cc_users: List[Dict[str, str]] = []
        bcc_users: List[Dict[str, str]] = []
        cc_addresses: List[str] = []
        bcc_addresses: List[str] = []
        matched_recipient_rules: List[Dict[str, Any]] = []
        resolve_warnings = list(load_warnings)

        if matched_rule_ids:
            cc_user_ids, bcc_user_ids = _merge_recipient_user_ids(
                matched_rule_ids=matched_rule_ids,
                rules_by_id=rules_by_id,
            )
            all_user_ids = _dedupe_preserve_order(cc_user_ids + bcc_user_ids)
            all_user_mappings, _, mapping_warnings = await _resolve_user_email_mappings(
                all_user_ids
            )
            resolve_warnings.extend(mapping_warnings)

            users_by_id = _build_users_by_id_lookup(all_user_mappings)
            cc_users, cc_addresses = _map_user_ids_to_users(cc_user_ids, users_by_id)
            bcc_users, bcc_addresses = _map_user_ids_to_users(bcc_user_ids, users_by_id)
            matched_recipient_rules = _build_matched_recipient_rules(
                matched_rule_ids=matched_rule_ids,
                rules_by_id=rules_by_id,
                users_by_id=users_by_id,
            )

        resolved = _apply_inbound_preserving_recipients(
            context,
            rule_cc=cc_addresses,
            rule_bcc=bcc_addresses,
            cc_user_ids=cc_user_ids,
            bcc_user_ids=bcc_user_ids,
            cc_users=cc_users,
            bcc_users=bcc_users,
            matched_rule_ids=matched_rule_ids,
            matched_recipient_rules=matched_recipient_rules,
            decision_source=decision_source,
            reason=llm_result.get("reason", "") or "",
        )

        logger.info(
            f"ai_recipients_generator_node completed thread_id={thread_id} "
            f"decision_source={decision_source} matched_rules={len(matched_rule_ids)} "
            f"to={len(resolved['to'])} cc={len(resolved['cc'])} bcc={len(resolved['bcc'])}"
        )

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_AI_RECIPIENTS_GENERATOR,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "recipient_rules_registered": True,
                "configured_recipient_rule_ids": recipient_rule_ids,
                "registered_recipient_rules": registered_rules,
                "llm_rules_sent_to_model": summarize_recipient_rules_for_llm(active_rules),
                "llm_matched_rules": matched_rules,
                "matched_recipient_rules": matched_recipient_rules,
                "llm_decision": decision_source,
                "llm_model": llm_result.get("llm_model", ""),
                "llm_attempts": llm_result.get("attempts", 0),
                "recipients": context["recipients"],
                "warnings": resolve_warnings,
                "llm_raw_response_preview": (llm_result.get("llm_raw_response") or "")[:500],
                "context": context,
                "downstream_hints": {
                    "generate_email": {
                        "uses": ["thread", "routing", "recipients", "kb_chunks", "tool_results"],
                    },
                },
            },
            "error": llm_result.get("error"),
        }
        return context, node_log

    except Exception as exc:
        logger.error(
            f"ai_recipients_generator_node failed thread_id={thread_id} "
            f"recipient_rule_ids={recipient_rule_ids}: {exc}",
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
            "node_type": NODE_TYPE_AI_RECIPIENTS_GENERATOR,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
