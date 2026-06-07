import asyncio
import json
import re
from typing import Any, Dict, List, Set, Tuple

from pydantic import BaseModel, Field

from config.llm_models_config import resolve_model_handler
from logging_config import get_logger
from services.email_agent_services.email_flows.email_department_router_llm_services import (
    format_thread_messages_for_routing,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_FLOW_REASONING_LLM_MODELS,
    EMAIL_ROUTER_LLM_MAX_RETRIES,
    EMAIL_ROUTER_LLM_RETRY_DELAY_SECONDS,
    EMAIL_ROUTER_MESSAGE_LIMIT,
)
from services.email_agent_services.email_recipient_rules.email_recipient_rules_mongo_services import (
    get_recipient_rule_id_str,
)
from services.open_ai_services import (
    openai_chat_completion_reasoning,
    openai_structured_output,
)

logger = get_logger()

_JSON_ARRAY_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*(\[.*?\])\s*```",
    re.DOTALL | re.IGNORECASE,
)
_JSON_OBJECT_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)

EMAIL_RECIPIENT_RULES_SYSTEM_PROMPT = """You are an AI recipient rule evaluator for email support.

Your job is to decide which recipient rules apply to the current email thread based on each rule's recipient_prompt.

Output JSON only: a JSON array of objects for rules that clearly match. Each object must use this exact shape:
{"_id": "<rule mongo id>", "meets_requirements": true}

Rules for your decision:
- Read each rule's recipient_prompt to decide whether the thread satisfies that condition.
- Give the **most weight** to the latest inbound customer message (IS_LATEST_INBOUND=true).
- Also consider the trigger message (IS_TRIGGER_MESSAGE=true) when present.
- Only include rules where the condition clearly applies — omit rules that do not match.
- Do NOT include rules with meets_requirements: false.
- Return an empty array [] when no rules match.
- _id must be copied exactly from the rules list. Never invent ids."""


class RecipientRuleMatchItem(BaseModel):
    id: str = Field(alias="_id")
    meets_requirements: bool = True

    class Config:
        populate_by_name = True


class RecipientRulesLLMResponse(BaseModel):
    matches: List[RecipientRuleMatchItem] = Field(default_factory=list)


def summarize_recipient_rules_for_llm(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summarized: List[Dict[str, Any]] = []
    for rule in rules:
        summarized.append({
            "_id": get_recipient_rule_id_str(rule),
            "rule_name": (rule.get("rule_name") or "").strip(),
            "recipient_prompt": (rule.get("recipient_prompt") or "").strip(),
        })
    return summarized


def format_recipient_rules_for_llm(rules: List[Dict[str, Any]]) -> str:
    lines = [f"RECIPIENT_RULE_COUNT: {len(rules)}", ""]
    for index, rule in enumerate(rules, start=1):
        lines.extend([
            f"--- Rule {index} ---",
            f"_id: {get_recipient_rule_id_str(rule)}",
            f"rule_name: {(rule.get('rule_name') or '').strip()}",
            f"recipient_prompt: {(rule.get('recipient_prompt') or '').strip()}",
            "",
        ])
    return "\n".join(lines).strip()


def build_recipient_rules_user_message(
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
        format_thread_messages_for_routing(
            messages,
            limit=EMAIL_ROUTER_MESSAGE_LIMIT,
        ),
        "",
        "RECIPIENT_RULES:",
        format_recipient_rules_for_llm(llm_rules),
        "",
        (
            "Evaluate which recipient rules apply to this thread. "
            "Return JSON only: an array of matching rules, e.g. "
            '[{"_id": "<rule id>", "meets_requirements": true}]. '
            "Omit non-matching rules. Return [] when none match."
        ),
    ])


def _normalize_meets_requirements(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0", "null", "none", ""}:
            return False
    return bool(value)


def _coerce_match_item(raw_item: Any) -> Dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None

    rule_id = (
        raw_item.get("_id")
        or raw_item.get("id")
        or raw_item.get("recipient_rule_id")
        or raw_item.get("rule_id")
    )
    normalized_rule_id = str(rule_id).strip() if rule_id is not None else ""
    if not normalized_rule_id:
        return None

    meets_requirements = _normalize_meets_requirements(
        raw_item.get("meets_requirements", True)
    )
    if not meets_requirements:
        return None

    return {
        "_id": normalized_rule_id,
        "meets_requirements": True,
    }


def _extract_json_array(raw_text: str) -> List[Any]:
    normalized = (raw_text or "").strip()
    if not normalized:
        raise ValueError("LLM returned empty recipient rules response.")

    candidates: List[str] = [normalized]

    array_block_match = _JSON_ARRAY_BLOCK_PATTERN.search(normalized)
    if array_block_match:
        candidates.insert(0, array_block_match.group(1).strip())

    object_block_match = _JSON_OBJECT_BLOCK_PATTERN.search(normalized)
    if object_block_match:
        candidates.insert(0, object_block_match.group(1).strip())

    array_start = normalized.find("[")
    array_end = normalized.rfind("]")
    if array_start != -1 and array_end != -1 and array_end > array_start:
        candidates.append(normalized[array_start:array_end + 1])

    object_start = normalized.find("{")
    object_end = normalized.rfind("}")
    if object_start != -1 and object_end != -1 and object_end > object_start:
        candidates.append(normalized[object_start:object_end + 1])

    last_error = ""
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                for key in ("matches", "matching_rules", "rules", "results", "data"):
                    nested = parsed.get(key)
                    if isinstance(nested, list):
                        return nested
                single_match = _coerce_match_item(parsed)
                if single_match:
                    return [single_match]
                last_error = "Parsed recipient JSON object did not contain a rule array."
                continue
            last_error = "Parsed recipient JSON was not an array or object."
        except json.JSONDecodeError as exc:
            last_error = str(exc)

    raise ValueError(last_error or "Failed to parse recipient rules JSON from LLM response.")


def parse_recipient_rules_response(
    *,
    raw_content: str,
    allowed_rule_ids: Set[str],
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Parse LLM recipient-rule JSON array.

    Returns:
        (matched_rules, validation_note)
        - matched_rules: only rules with meets_requirements=true and known _id
        - raises ValueError on invalid parse or unknown rule id
    """
    raw_items = _extract_json_array(raw_content)
    matched_rules: List[Dict[str, Any]] = []
    seen_rule_ids: Set[str] = set()

    for raw_item in raw_items:
        match_item = _coerce_match_item(raw_item)
        if not match_item:
            continue

        rule_id = match_item["_id"]
        if rule_id in seen_rule_ids:
            continue

        if rule_id not in allowed_rule_ids:
            raise ValueError(
                f"LLM returned unknown recipient rule _id '{rule_id}'. "
                f"Allowed: {sorted(allowed_rule_ids)}"
            )

        seen_rule_ids.add(rule_id)
        matched_rules.append(match_item)

    if matched_rules:
        return matched_rules, f"LLM matched {len(matched_rules)} recipient rule(s)."

    return [], "LLM returned no matching recipient rules."


def _validate_llm_model(llm_model: str) -> str:
    normalized = (llm_model or "").strip()
    if not normalized:
        raise ValueError("agent.llm_model is required for AI Recipients Generator.")

    if normalized not in EMAIL_FLOW_REASONING_LLM_MODELS:
        allowed = ", ".join(sorted(EMAIL_FLOW_REASONING_LLM_MODELS))
        raise ValueError(
            f"Unsupported llm_model '{normalized}' for recipient rules evaluation. "
            f"Allowed models: {allowed}."
        )

    _, model_config = resolve_model_handler(normalized)
    if model_config.get("mode") != "reasoning":
        raise ValueError(
            f"llm_model '{normalized}' must be a reasoning model for recipient rules evaluation."
        )

    return normalized


async def _call_recipient_rules_llm_once(
    *,
    llm_model: str,
    user_message: str,
) -> str:
    messages = [
        {"role": "system", "content": EMAIL_RECIPIENT_RULES_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        parsed = await openai_structured_output(
            model=llm_model,
            messages=messages,
            response_format=RecipientRulesLLMResponse,
        )
        matches = parsed.get("matches") or []
        normalized_matches = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            coerced = _coerce_match_item(match)
            if coerced:
                normalized_matches.append(coerced)
        return json.dumps(normalized_matches)
    except Exception as structured_exc:
        logger.warning(
            f"Structured recipient rules parse failed for model={llm_model}: {structured_exc}. "
            "Falling back to reasoning JSON completion."
        )

    raw_response = await openai_chat_completion_reasoning({
        "model": llm_model,
        "messages": messages,
    })
    return (raw_response or "").strip()


async def evaluate_recipient_rules_with_llm(
    *,
    context: Dict[str, Any],
    llm_rules: List[Dict[str, Any]],
    llm_model: str,
) -> Dict[str, Any]:
    """
    Run recipient-rule LLM evaluation with retries.

    decision_source values:
      - llm_matched: one or more rules matched
      - llm_no_match: parsed empty array from LLM
      - safety_empty: LLM/parsing failed after retries
    """
    validated_model = _validate_llm_model(llm_model)
    allowed_rule_ids = {
        get_recipient_rule_id_str(rule)
        for rule in llm_rules
        if get_recipient_rule_id_str(rule)
    }

    if not llm_rules:
        return {
            "matched_rules": [],
            "decision_source": "safety_empty",
            "reason": "No recipient rules available for LLM evaluation.",
            "llm_model": validated_model,
            "attempts": 0,
            "llm_raw_response": "",
            "error": None,
        }

    user_message = build_recipient_rules_user_message(
        context=context,
        llm_rules=llm_rules,
    )

    logger.info(
        f"Recipient rules LLM started model={validated_model} "
        f"rules={len(llm_rules)} allowed_rule_ids={len(allowed_rule_ids)}"
    )

    last_error = ""
    attempts = 0
    last_raw_response = ""

    for attempt in range(1, EMAIL_ROUTER_LLM_MAX_RETRIES + 1):
        attempts = attempt
        try:
            last_raw_response = await _call_recipient_rules_llm_once(
                llm_model=validated_model,
                user_message=user_message,
            )
            matched_rules, validation_note = parse_recipient_rules_response(
                raw_content=last_raw_response,
                allowed_rule_ids=allowed_rule_ids,
            )

            if not matched_rules:
                logger.info(
                    f"Recipient rules LLM attempt {attempt}: no matching rules"
                )
                return {
                    "matched_rules": [],
                    "decision_source": "llm_no_match",
                    "reason": validation_note,
                    "llm_model": validated_model,
                    "attempts": attempts,
                    "llm_raw_response": last_raw_response,
                    "error": None,
                }

            logger.info(
                f"Recipient rules LLM attempt {attempt}: matched "
                f"{len(matched_rules)} rule(s)"
            )
            return {
                "matched_rules": matched_rules,
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
                f"Recipient rules LLM attempt {attempt} failed: {exc}",
                exc_info=True,
            )

        if attempt < EMAIL_ROUTER_LLM_MAX_RETRIES:
            await asyncio.sleep(EMAIL_ROUTER_LLM_RETRY_DELAY_SECONDS * attempt)

    logger.warning(
        f"Recipient rules evaluation leaving matches empty after LLM failures. "
        f"Last error: {last_error}"
    )
    return {
        "matched_rules": [],
        "decision_source": "safety_empty",
        "reason": (
            f"LLM recipient rules evaluation failed after {EMAIL_ROUTER_LLM_MAX_RETRIES} "
            "attempts."
        ),
        "llm_model": validated_model,
        "attempts": attempts,
        "llm_raw_response": last_raw_response,
        "error": last_error or "LLM recipient rules evaluation failed.",
    }
