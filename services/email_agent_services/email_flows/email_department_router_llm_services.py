import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from config.llm_models_config import resolve_model_handler
from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_FLOW_REASONING_LLM_MODELS,
    EMAIL_ROUTER_LLM_MAX_RETRIES,
    EMAIL_ROUTER_LLM_RETRY_DELAY_SECONDS,
    EMAIL_ROUTER_MESSAGE_LIMIT,
)
from services.email_agent_services.email_routing_rules.email_routing_rules_mongo_services import (
    get_routing_rule_id_str,
)
from services.open_ai_services import (
    openai_chat_completion_reasoning,
    openai_structured_output,
)

logger = get_logger()

_JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

EMAIL_DEPARTMENT_ROUTER_SYSTEM_PROMPT = """You are an email department routing assistant.

Your job is to pick the single best department_id for the current email thread from the routing rules provided — or return null when none of the rules clearly apply.

Output JSON only with this exact shape:
{"department_id": "<mongo department id string>"}  OR  {"department_id": null}

Rules for your decision:
- Read each rule's routing_prompt to decide whether the thread belongs in that department.
- Give the **most weight** to the latest inbound customer message (IS_LATEST_INBOUND).
- Match based on what the customer is asking **now** in that latest inbound message.
- Examples: "what are your prices" → pricing rule; "ticket status" / bug report → technical support rule.
- If multiple rules match, pick the department from the rule with the **lowest priority number** (priority 10 beats priority 50).
- Only return null when **no** rule's routing_prompt applies to the thread.
- department_id must be copied exactly from the rules list. Never invent ids."""


class DepartmentRoutingLLMResponse(BaseModel):
    department_id: Optional[str] = Field(
        default=None,
        description="Selected department Mongo id, or null when no rule clearly applies.",
    )


def _get_rule_department_id(rule: Dict[str, Any]) -> str:
    return (rule.get("department_id") or "").strip()


def _normalize_nullable_department_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or normalized.lower() in {"null", "none", "nil"}:
            return None
        return normalized
    return None


def summarize_routing_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summarized: List[Dict[str, Any]] = []
    for rule in rules:
        summarized.append({
            "routing_rule_id": get_routing_rule_id_str(rule),
            "department_id": _get_rule_department_id(rule),
            "rule_name": (rule.get("rule_name") or "").strip(),
            "routing_prompt": (rule.get("routing_prompt") or "").strip(),
            "priority": int(rule.get("priority", 100)),
            "is_fallback": bool(rule.get("is_fallback", False)),
            "status": (rule.get("status") or "").strip(),
        })
    return summarized


def _find_last_inbound_message_id(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages):
        if (message.get("direction") or "").strip().lower() == "inbound":
            return (message.get("message_id") or "").strip()
    return ""


def format_thread_messages_for_routing(
    messages: List[Dict[str, Any]],
    *,
    limit: int = EMAIL_ROUTER_MESSAGE_LIMIT,
) -> str:
    recent_messages = messages[-limit:] if len(messages) > limit else list(messages)
    last_inbound_message_id = _find_last_inbound_message_id(recent_messages)

    lines = [f"RECENT_EMAIL_COUNT: {len(recent_messages)}", ""]
    for index, message in enumerate(recent_messages, start=1):
        direction = (message.get("direction") or "unknown").strip()
        is_latest_inbound = (
            direction == "inbound"
            and (message.get("message_id") or "").strip() == last_inbound_message_id
        )
        flags = []
        if is_latest_inbound:
            flags.append("IS_LATEST_INBOUND=true")
        if message.get("is_trigger"):
            flags.append("IS_TRIGGER_MESSAGE=true")
        flag_text = " | ".join(flags) if flags else "IS_LATEST_INBOUND=false"

        body_text = (message.get("body_text") or message.get("snippet") or "").strip()
        lines.extend([
            f"--- Email {index} of {len(recent_messages)} ---",
            f"Direction: {direction}",
            f"From: {message.get('from', '')}",
            f"Received: {message.get('received_at', '')}",
            flag_text,
            "Body:",
            body_text or "(empty)",
            "",
        ])

    return "\n".join(lines).strip()


def format_routing_rules_for_llm(rules: List[Dict[str, Any]]) -> str:
    sorted_rules = sorted(
        rules,
        key=lambda rule: (int(rule.get("priority", 100)), get_routing_rule_id_str(rule)),
    )
    lines = [f"ROUTING_RULE_COUNT: {len(sorted_rules)}", ""]
    for index, rule in enumerate(sorted_rules, start=1):
        lines.extend([
            f"--- Rule {index} ---",
            f"department_id: {_get_rule_department_id(rule)}",
            f"rule_name: {(rule.get('rule_name') or '').strip()}",
            f"priority: {int(rule.get('priority', 100))}",
            f"routing_prompt: {(rule.get('routing_prompt') or '').strip()}",
            "",
        ])
    return "\n".join(lines).strip()


def build_department_router_user_message(
    *,
    context: Dict[str, Any],
    llm_rules: List[Dict[str, Any]],
) -> str:
    thread = context.get("thread") or {}
    messages = thread.get("messages") or []
    subject = (thread.get("subject") or "").strip()

    return "\n\n".join([
        f"THREAD_SUBJECT: {subject or '(unknown)'}",
        "",
        "RECENT_THREAD_EMAILS:",
        format_thread_messages_for_routing(messages),
        "",
        "ROUTING_RULES:",
        format_routing_rules_for_llm(llm_rules),
        "",
        (
            "Select the best department_id for this thread using the rules above. "
            "Return JSON only: {\"department_id\": \"<id>\"} or {\"department_id\": null}."
        ),
    ])


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    normalized = (raw_text or "").strip()
    if not normalized:
        raise ValueError("LLM returned empty routing response.")

    candidates = [normalized]
    block_match = _JSON_BLOCK_PATTERN.search(normalized)
    if block_match:
        candidates.insert(0, block_match.group(1).strip())

    start = normalized.find("{")
    end = normalized.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(normalized[start:end + 1])

    last_error = ""
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            last_error = "Parsed routing JSON was not an object."
        except json.JSONDecodeError as exc:
            last_error = str(exc)

    raise ValueError(last_error or "Failed to parse routing JSON from LLM response.")


def parse_department_routing_response(
    *,
    raw_content: str,
    allowed_department_ids: Set[str],
) -> Tuple[Optional[str], str]:
    """
    Parse LLM routing JSON.

    Returns:
        (department_id, validation_note)
        - department_id None = explicit no-match
        - raises ValueError on invalid parse or unknown department id
    """
    payload = _extract_json_object(raw_content)
    department_id = _normalize_nullable_department_id(payload.get("department_id"))

    if department_id is None:
        return None, "LLM returned department_id null."

    if department_id not in allowed_department_ids:
        raise ValueError(
            f"LLM returned unknown department_id '{department_id}'. "
            f"Allowed: {sorted(allowed_department_ids)}"
        )

    return department_id, "LLM matched department."


def _validate_llm_model(llm_model: str) -> str:
    normalized = (llm_model or "").strip()
    if not normalized:
        raise ValueError("agent.llm_model is required for AI Department Router.")

    if normalized not in EMAIL_FLOW_REASONING_LLM_MODELS:
        allowed = ", ".join(sorted(EMAIL_FLOW_REASONING_LLM_MODELS))
        raise ValueError(
            f"Unsupported llm_model '{normalized}' for department routing. "
            f"Allowed models: {allowed}."
        )

    _, model_config = resolve_model_handler(normalized)
    if model_config.get("mode") != "reasoning":
        raise ValueError(
            f"llm_model '{normalized}' must be a reasoning model for department routing."
        )

    return normalized


def _find_rule_for_department(
    rules: List[Dict[str, Any]],
    department_id: str,
) -> Optional[Dict[str, Any]]:
    matches = [
        rule for rule in rules
        if _get_rule_department_id(rule) == department_id
    ]
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda rule: (int(rule.get("priority", 100)), get_routing_rule_id_str(rule)),
    )[0]


def _find_fallback_rule(rules: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    fallback_rules = [
        rule for rule in rules
        if bool(rule.get("is_fallback")) and _get_rule_department_id(rule)
    ]
    if not fallback_rules:
        return None
    return sorted(
        fallback_rules,
        key=lambda rule: (int(rule.get("priority", 100)), get_routing_rule_id_str(rule)),
    )[0]


async def _call_routing_llm_once(
    *,
    llm_model: str,
    user_message: str,
) -> str:
    messages = [
        {"role": "system", "content": EMAIL_DEPARTMENT_ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        parsed = await openai_structured_output(
            model=llm_model,
            messages=messages,
            response_format=DepartmentRoutingLLMResponse,
        )
        return json.dumps(parsed)
    except Exception as structured_exc:
        logger.warning(
            f"Structured routing parse failed for model={llm_model}: {structured_exc}. "
            "Falling back to reasoning JSON completion."
        )

    raw_response = await openai_chat_completion_reasoning({
        "model": llm_model,
        "messages": messages,
    })
    return (raw_response or "").strip()


async def route_department_with_llm(
    *,
    context: Dict[str, Any],
    llm_rules: List[Dict[str, Any]],
    fallback_rule: Optional[Dict[str, Any]],
    llm_model: str,
) -> Dict[str, Any]:
    """
    Run department routing LLM with retries and safety nets.

    decision_source values:
      - llm_matched: parsed department_id from LLM
      - llm_no_match: parsed null from LLM (leave department empty)
      - fallback_rule: LLM/parsing failed; used is_fallback rule
      - safety_empty: all safety nets failed; department left empty
    """
    validated_model = _validate_llm_model(llm_model)
    allowed_department_ids = {
        _get_rule_department_id(rule)
        for rule in llm_rules
        if _get_rule_department_id(rule)
    }

    if not llm_rules:
        return {
            "department_id": "",
            "routing_rule_id": "",
            "rule_name": "",
            "decision_source": "safety_empty",
            "reason": "No non-fallback routing rules available for LLM routing.",
            "llm_model": validated_model,
            "attempts": 0,
            "llm_raw_response": "",
            "error": None,
        }

    user_message = build_department_router_user_message(
        context=context,
        llm_rules=llm_rules,
    )

    logger.info(
        f"Department router LLM started model={validated_model} "
        f"rules={len(llm_rules)} allowed_departments={len(allowed_department_ids)}"
    )

    last_error = ""
    attempts = 0
    last_raw_response = ""

    for attempt in range(1, EMAIL_ROUTER_LLM_MAX_RETRIES + 1):
        attempts = attempt
        try:
            last_raw_response = await _call_routing_llm_once(
                llm_model=validated_model,
                user_message=user_message,
            )
            department_id, validation_note = parse_department_routing_response(
                raw_content=last_raw_response,
                allowed_department_ids=allowed_department_ids,
            )

            if department_id is None:
                logger.info(
                    f"Department router LLM attempt {attempt}: explicit no-match (null department_id)"
                )
                return {
                    "department_id": "",
                    "routing_rule_id": "",
                    "rule_name": "",
                    "decision_source": "llm_no_match",
                    "reason": validation_note,
                    "llm_model": validated_model,
                    "attempts": attempts,
                    "llm_raw_response": last_raw_response,
                    "error": None,
                }

            matched_rule = _find_rule_for_department(llm_rules, department_id)
            logger.info(
                f"Department router LLM attempt {attempt}: matched department_id={department_id} "
                f"rule={matched_rule.get('rule_name') if matched_rule else 'unknown'}"
            )
            return {
                "department_id": department_id,
                "routing_rule_id": (
                    get_routing_rule_id_str(matched_rule) if matched_rule else ""
                ),
                "rule_name": (matched_rule.get("rule_name") or "").strip() if matched_rule else "",
                "decision_source": "llm_matched",
                "reason": validation_note,
                "llm_model": validated_model,
                "attempts": attempts,
                "llm_raw_response": last_raw_response,
                "error": None,
            }

        except Exception as exc:
            last_error = str(exc)
            logger.error(
                f"Department router LLM attempt {attempt} failed: {exc}",
                exc_info=True,
            )

        if attempt < EMAIL_ROUTER_LLM_MAX_RETRIES:
            await asyncio.sleep(EMAIL_ROUTER_LLM_RETRY_DELAY_SECONDS * attempt)

    if fallback_rule and _get_rule_department_id(fallback_rule):
        fallback_department_id = _get_rule_department_id(fallback_rule)
        logger.warning(
            f"Department router using fallback rule after LLM failures "
            f"(rule={fallback_rule.get('rule_name')}, department_id={fallback_department_id})"
        )
        return {
            "department_id": fallback_department_id,
            "routing_rule_id": get_routing_rule_id_str(fallback_rule),
            "rule_name": (fallback_rule.get("rule_name") or "").strip(),
            "decision_source": "fallback_rule",
            "reason": (
                f"LLM routing failed after {EMAIL_ROUTER_LLM_MAX_RETRIES} attempts; "
                f"used is_fallback rule. Last error: {last_error}"
            ),
            "llm_model": validated_model,
            "attempts": attempts,
            "llm_raw_response": last_raw_response,
            "error": last_error or "LLM routing failed.",
        }

    logger.warning(
        f"Department router leaving department empty after LLM failures. "
        f"Last error: {last_error}"
    )
    return {
        "department_id": "",
        "routing_rule_id": "",
        "rule_name": "",
        "decision_source": "safety_empty",
        "reason": (
            f"LLM routing failed after {EMAIL_ROUTER_LLM_MAX_RETRIES} attempts and "
            "no fallback rule was available."
        ),
        "llm_model": validated_model,
        "attempts": attempts,
        "llm_raw_response": last_raw_response,
        "error": last_error or "LLM routing failed.",
    }
