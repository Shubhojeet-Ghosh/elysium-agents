import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from config.llm_models_config import MODEL_REGISTRY, resolve_model_handler
from logging_config import get_logger
from services.email_agent_services.email_flows.email_department_router_llm_services import (
    format_thread_messages_for_routing,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_GENERATE_LLM_MAX_RETRIES,
    EMAIL_GENERATE_LLM_RETRY_DELAY_SECONDS,
    EMAIL_GENERATE_FALLBACK_CONFIDENCE,
    EMAIL_GENERATE_FALLBACK_DRAFT,
    EMAIL_GENERATE_MAX_CONFIDENCE,
    EMAIL_GENERATE_MIN_CONFIDENCE,
    EMAIL_ROUTER_MESSAGE_LIMIT,
)
from services.open_ai_services import (
    openai_structured_output,
)

logger = get_logger()

_JSON_OBJECT_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)
_EMAIL_IN_ANGLE_BRACKETS_PATTERN = re.compile(r"^(.+?)\s*<[^>]+>$")
_EMAIL_ADDRESS_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

EMAIL_GENERATE_FIXED_SYSTEM_PROMPT = """You are an email reply writer for a customer support team.

Your job is to draft the **body** of a reply email to the customer using only the context provided.

Rules:
- Address the customer's **latest inbound / trigger message** directly.
- Use KNOWLEDGE_SNIPPETS and successful TOOL_RESULTS when relevant. Do not invent facts.
- If information is missing, acknowledge that honestly in the draft and assign a **lower confidence**.
- When EMAIL_FORMAT_TEMPLATE is provided, follow its structure and replace all {{placeholders}} with appropriate content.
  The final email_draft must not contain unresolved {{placeholders}}.
- Write plain-text email body only (no To/Cc/Bcc headers).
- Output JSON only with this exact shape:
  {"email_draft": "<full reply body>", "confidence": <number>}

Confidence rubric (how safe it is to auto-send this reply without human review):
- 0.9–1.0: Question clearly answered; strong KB/tool support; no guesswork.
- 0.7–0.89: Reasonable reply; minor gaps or generic KB coverage.
- 0.5–0.69: Partial answer; some customer questions unanswered.
- 0.3–0.49: Mostly acknowledgment or follow-up promise; insufficient facts.
- 0.1–0.29: Should not auto-send; high risk of wrong or empty answer.

confidence must be a number between 0.1 and 1.0."""


class GenerateEmailLLMResponse(BaseModel):
    email_draft: str = Field(
        ...,
        description="Full plain-text reply email body with all template placeholders resolved.",
    )
    confidence: float = Field(
        ...,
        ge=0.1,
        le=1.0,
        description="Auto-send safety score from 0.1 (unsafe) to 1.0 (very safe).",
    )


def stringify_llm_messages(messages: List[Dict[str, str]]) -> str:
    """Serialize the full LLM message list for run-log audit."""
    parts: List[str] = []
    for index, message in enumerate(messages, start=1):
        role = (message.get("role") or "unknown").strip().upper()
        content = message.get("content") or ""
        parts.extend([
            f"--- Message {index} | role={role} ---",
            content,
            "",
        ])
    return "\n".join(parts).strip()


def _validate_llm_model(llm_model: str) -> str:
    normalized = (llm_model or "").strip()
    if not normalized:
        raise ValueError("agent.llm_model is required for Generate Email.")

    if normalized not in MODEL_REGISTRY:
        allowed = ", ".join(sorted(MODEL_REGISTRY.keys()))
        raise ValueError(
            f"Unsupported llm_model '{normalized}' for email generation. "
            f"Allowed models: {allowed}."
        )

    return normalized


def _guess_customer_name(from_or_reply_to: str) -> str:
    normalized = (from_or_reply_to or "").strip()
    if not normalized:
        return "there"

    angle_match = _EMAIL_IN_ANGLE_BRACKETS_PATTERN.match(normalized)
    if angle_match:
        name = angle_match.group(1).strip().strip('"').strip("'")
        if name:
            return name

    if _EMAIL_ADDRESS_PATTERN.match(normalized):
        local_part = normalized.split("@", 1)[0]
        cleaned = local_part.replace(".", " ").replace("_", " ").strip()
        if cleaned:
            return cleaned.title()

    return normalized.split("@", 1)[0].strip() or "there"


def _resolve_reply_target(context: Dict[str, Any]) -> Tuple[str, str]:
    recipients = context.get("recipients") or {}
    to_addresses = recipients.get("to") or []
    reply_to = (to_addresses[0] if to_addresses else "").strip()

    trigger_message = context.get("trigger_message") or {}
    latest_inbound = (context.get("thread") or {}).get("latest_inbound") or {}

    if not reply_to:
        reply_to = (trigger_message.get("reply_to") or latest_inbound.get("reply_to") or "").strip()
    if not reply_to:
        reply_to = (trigger_message.get("from") or latest_inbound.get("from") or "").strip()

    return reply_to, _guess_customer_name(reply_to)


def _format_kb_snippets(context: Dict[str, Any]) -> str:
    kb_title = (context.get("kb_title") or "").strip()
    kb_chunks = context.get("kb_chunks") or []

    lines = [f"KNOWLEDGE_BASE: {kb_title or '(none)'}"]
    if not kb_chunks:
        lines.append("(no knowledge snippets retrieved)")
        return "\n".join(lines)

    lines.append("")
    for index, chunk in enumerate(kb_chunks, start=1):
        text_content = (chunk.get("text_content") or "").strip()
        score = chunk.get("score")
        score_text = f" (score={score})" if score is not None else ""
        lines.append(f"[{index}]{score_text} {text_content or '(empty)'}")

    return "\n".join(lines)


def _format_tool_results(context: Dict[str, Any]) -> Tuple[str, str]:
    tool_results = context.get("tool_results") or []
    if not tool_results:
        return "(none)", "(none)"

    successful_lines: List[str] = []
    failed_lines: List[str] = []

    for result in tool_results:
        tool_name = (result.get("tool_name") or result.get("display_name") or "unknown_tool").strip()
        if result.get("success"):
            response_payload = result.get("response")
            if isinstance(response_payload, (dict, list)):
                response_text = json.dumps(response_payload, ensure_ascii=False)
            else:
                response_text = str(response_payload or result.get("message") or "")
            successful_lines.append(
                f"- {tool_name}: {response_text[:4000]}"
            )
        else:
            message = (result.get("message") or "call failed").strip()
            failed_lines.append(f"- {tool_name}: {message}")

    successful_block = "\n".join(successful_lines) if successful_lines else "(none)"
    failed_block = "\n".join(failed_lines) if failed_lines else "(none)"
    return successful_block, failed_block


def build_generate_email_messages(
    *,
    context: Dict[str, Any],
) -> List[Dict[str, str]]:
    thread = context.get("thread") or {}
    messages = thread.get("messages") or []
    subject = (thread.get("subject") or "").strip()
    compressed_query = (context.get("compressed_query") or "").strip()
    agent_system_prompt = (context.get("system_prompt") or "").strip()
    email_format_template = (context.get("email_format_template") or "").strip()
    reply_to, customer_name = _resolve_reply_target(context)

    successful_tools, failed_tools = _format_tool_results(context)

    user_sections = [
        f"THREAD_SUBJECT: {subject or '(unknown)'}",
        f"REPLY_TO: {reply_to or '(unknown)'}",
        f"CUSTOMER_NAME_HINT: {customer_name}",
        "",
        "COMPRESSED_THREAD_SUMMARY:",
        compressed_query or "(empty)",
        "",
        "RECENT_THREAD_EMAILS:",
        format_thread_messages_for_routing(
            messages,
            limit=EMAIL_ROUTER_MESSAGE_LIMIT,
        ),
        "",
        _format_kb_snippets(context),
        "",
        "TOOL_RESULTS (successful only):",
        successful_tools,
        "",
        "TOOLS_FAILED_OR_UNAVAILABLE:",
        failed_tools,
        "",
    ]

    if email_format_template:
        user_sections.extend([
            "EMAIL_FORMAT_TEMPLATE:",
            email_format_template,
            "",
        ])

    user_sections.append(
        "Draft the reply email body to the latest inbound / trigger message. "
        'Return JSON only: {"email_draft": "...", "confidence": 0.0}'
    )

    system_content = EMAIL_GENERATE_FIXED_SYSTEM_PROMPT
    if agent_system_prompt:
        system_content = "\n\n".join([
            EMAIL_GENERATE_FIXED_SYSTEM_PROMPT,
            "AGENT_SYSTEM_PROMPT:",
            agent_system_prompt,
        ])

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "\n".join(user_sections).strip()},
    ]


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return EMAIL_GENERATE_MIN_CONFIDENCE

    if confidence < EMAIL_GENERATE_MIN_CONFIDENCE:
        return EMAIL_GENERATE_MIN_CONFIDENCE
    if confidence > EMAIL_GENERATE_MAX_CONFIDENCE:
        return EMAIL_GENERATE_MAX_CONFIDENCE
    return confidence


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    normalized = (raw_text or "").strip()
    if not normalized:
        raise ValueError("LLM returned empty email generation response.")

    candidates = [normalized]
    block_match = _JSON_OBJECT_BLOCK_PATTERN.search(normalized)
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
            last_error = "Parsed email generation JSON was not an object."
        except json.JSONDecodeError as exc:
            last_error = str(exc)

    raise ValueError(last_error or "Failed to parse email generation JSON from LLM response.")


def parse_generate_email_response(raw_content: str) -> Tuple[str, float, str]:
    """
    Parse LLM email generation JSON.

    Returns:
        (email_draft, confidence, validation_note)
    """
    payload = _extract_json_object(raw_content)
    email_draft = (payload.get("email_draft") or payload.get("body_text") or "").strip()
    if not email_draft:
        raise ValueError("LLM response missing non-empty email_draft.")

    confidence = _clamp_confidence(payload.get("confidence"))
    return email_draft, confidence, "LLM generated email draft."


def build_reply_subject(thread_subject: str) -> str:
    normalized = (thread_subject or "").strip()
    if not normalized:
        return "Re: (no subject)"
    if normalized.lower().startswith("re:"):
        return normalized
    return f"Re: {normalized}"


def build_fallback_generation_result(
    *,
    llm_model: str,
    thread_subject: str,
    reason: str,
    attempts: int,
    last_error: str,
    llm_raw_response: str,
    llm_prompt_text: str,
) -> Dict[str, Any]:
    return {
        "subject": build_reply_subject(thread_subject),
        "body_text": EMAIL_GENERATE_FALLBACK_DRAFT,
        "body_html": "",
        "confidence": EMAIL_GENERATE_FALLBACK_CONFIDENCE,
        "decision_source": "fallback_template",
        "reason": reason,
        "llm_model": llm_model,
        "attempts": attempts,
        "llm_raw_response": llm_raw_response,
        "llm_prompt_text": llm_prompt_text,
        "error": last_error or "LLM email generation failed.",
    }


async def _call_generate_email_llm_once(
    *,
    llm_model: str,
    messages: List[Dict[str, str]],
) -> str:
    try:
        parsed = await openai_structured_output(
            model=llm_model,
            messages=messages,
            response_format=GenerateEmailLLMResponse,
        )
        return json.dumps(parsed)
    except Exception as structured_exc:
        logger.warning(
            f"Structured email generation parse failed for model={llm_model}: {structured_exc}. "
            "Falling back to chat completion JSON."
        )

    handler, model_config = resolve_model_handler(llm_model)
    params: Dict[str, Any] = {
        "model": llm_model,
        "messages": messages,
    }
    if model_config.get("mode") != "reasoning":
        params["temperature"] = 0.3
    raw_response = await handler(params)

    return (raw_response or "").strip()


async def generate_email_with_llm(
    *,
    context: Dict[str, Any],
    llm_model: str,
) -> Dict[str, Any]:
    """
    Run email generation LLM with retries and fallback template safety net.

    decision_source values:
      - llm_generated: parsed email_draft from LLM
      - fallback_template: LLM/parsing failed after retries
    """
    validated_model = _validate_llm_model(llm_model)
    messages = build_generate_email_messages(context=context)
    llm_prompt_text = stringify_llm_messages(messages)
    thread_subject = ((context.get("thread") or {}).get("subject") or "").strip()

    logger.info(
        f"Generate email LLM started model={validated_model} "
        f"prompt_chars={len(llm_prompt_text)}"
    )

    last_error = ""
    attempts = 0
    last_raw_response = ""

    for attempt in range(1, EMAIL_GENERATE_LLM_MAX_RETRIES + 1):
        attempts = attempt
        try:
            last_raw_response = await _call_generate_email_llm_once(
                llm_model=validated_model,
                messages=messages,
            )
            email_draft, confidence, validation_note = parse_generate_email_response(
                last_raw_response
            )

            logger.info(
                f"Generate email LLM attempt {attempt}: success confidence={confidence} "
                f"draft_chars={len(email_draft)}"
            )
            return {
                "subject": build_reply_subject(thread_subject),
                "body_text": email_draft,
                "body_html": "",
                "confidence": confidence,
                "decision_source": "llm_generated",
                "reason": validation_note,
                "llm_model": validated_model,
                "attempts": attempts,
                "llm_raw_response": last_raw_response,
                "llm_prompt_text": llm_prompt_text,
                "error": None,
            }

        except Exception as exc:
            last_error = str(exc)
            logger.error(
                f"Generate email LLM attempt {attempt} failed: {exc}",
                exc_info=True,
            )

        if attempt < EMAIL_GENERATE_LLM_MAX_RETRIES:
            await asyncio.sleep(EMAIL_GENERATE_LLM_RETRY_DELAY_SECONDS * attempt)

    logger.warning(
        f"Generate email using fallback template after LLM failures. "
        f"Last error: {last_error}"
    )
    return build_fallback_generation_result(
        llm_model=validated_model,
        thread_subject=thread_subject,
        reason=(
            f"LLM email generation failed after {EMAIL_GENERATE_LLM_MAX_RETRIES} attempts; "
            "used fallback template."
        ),
        attempts=attempts,
        last_error=last_error,
        llm_raw_response=last_raw_response,
        llm_prompt_text=llm_prompt_text,
    )
