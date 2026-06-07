import asyncio
from typing import Any, Dict, List

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_COMPRESS_LLM_MODEL,
    EMAIL_COMPRESS_LLM_TEMPERATURE,
    EMAIL_COMPRESS_MAX_RETRIES,
    EMAIL_COMPRESS_PER_MESSAGE_CHAR_CAP,
    EMAIL_COMPRESS_RETRY_DELAY_SECONDS,
)
from services.email_agent_services.email_flows.email_flow_context import (
    build_compressed_query,
    get_stored_message_id,
)
from services.open_ai_services import openai_chat_completion_non_reasoning

logger = get_logger()

_SYSTEM_PROMPT = """You compress email thread history into one dense retrieval query.

The output will be embedded and used to:
- search a knowledge base (RAG)
- help an AI agent decide which tools to call
- route the conversation

Rules:
- Include EVERY important fact from the thread: names, order/ticket IDs, dates, amounts, products, deadlines, requests, complaints, and status updates — even if they appear in older messages.
- Give extra weight to the message marked IS_LATEST_ARRIVAL and IS_TRIGGER_MESSAGE.
- Write plain text only (no markdown, bullets, or JSON).
- Be concise but complete — prefer retaining factual details over filler.
- Target roughly 150–400 words unless the thread truly needs more."""


def _cap_body_text(body_text: str, cap: int = EMAIL_COMPRESS_PER_MESSAGE_CHAR_CAP) -> str:
    normalized = (body_text or "").strip()
    if len(normalized) <= cap:
        return normalized
    return f"{normalized[:cap]}\n\n[body truncated at {cap} characters]"


def format_thread_for_compress_llm(
    *,
    subject: str,
    messages: List[Dict[str, Any]],
    trigger_message_id: str = "",
) -> str:
    """
    Build the user-message text sent to the compression LLM.

    Uses full body_text per message (per-message char cap only). Marks the chronologically
    last message as IS_LATEST_ARRIVAL and the trigger message as IS_TRIGGER_MESSAGE.
    """
    normalized_subject = (subject or "").strip() or "(no subject)"
    total = len(messages)
    last_message_id = get_stored_message_id(messages[-1]) if messages else ""
    normalized_trigger_id = trigger_message_id.strip()

    lines = [
        f"THREAD_SUBJECT: {normalized_subject}",
        f"MESSAGE_COUNT: {total}",
        "",
    ]

    for index, message in enumerate(messages, start=1):
        stored_id = get_stored_message_id(message)
        direction = message.get("direction", "unknown")
        sender = message.get("from", "") or "(unknown sender)"
        received_at = message.get("received_at", "")
        if hasattr(received_at, "isoformat"):
            received_at = received_at.isoformat()

        flags: List[str] = []
        if stored_id == last_message_id:
            flags.append("IS_LATEST_ARRIVAL=true")
        if normalized_trigger_id and stored_id == normalized_trigger_id:
            flags.append("IS_TRIGGER_MESSAGE=true")
        if message.get("is_new"):
            flags.append("IS_NEW_SYNC=true")

        flag_line = " | ".join(flags) if flags else "IS_LATEST_ARRIVAL=false | IS_TRIGGER_MESSAGE=false"

        body_text = _cap_body_text(message.get("body_text", "") or "")

        lines.extend([
            f"--- Email {index} of {total} ---",
            f"Direction: {direction}",
            f"From: {sender}",
            f"Received: {received_at}",
            flag_line,
            "Body:",
            body_text,
            "",
        ])

    lines.append(
        "Write the single compressed retrieval query for this thread now. "
        "Include all important facts from every email above."
    )
    return "\n".join(lines)


async def compress_thread_query_with_llm(
    *,
    subject: str,
    messages: List[Dict[str, Any]],
    trigger_message: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Use gpt-4.1-mini to build compressed_query from the thread.

    Retries up to EMAIL_COMPRESS_MAX_RETRIES. Falls back to rule-based build_compressed_query
    if all attempts fail or return empty content.
    """
    trigger_message_id = get_stored_message_id(trigger_message)
    llm_input = format_thread_for_compress_llm(
        subject=subject,
        messages=messages,
        trigger_message_id=trigger_message_id,
    )

    messages_payload = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": llm_input},
    ]

    last_error = ""
    attempts = 0

    for attempt in range(1, EMAIL_COMPRESS_MAX_RETRIES + 1):
        attempts = attempt
        try:
            raw_response = await openai_chat_completion_non_reasoning({
                "model": EMAIL_COMPRESS_LLM_MODEL,
                "messages": messages_payload,
                "temperature": EMAIL_COMPRESS_LLM_TEMPERATURE,
            })

            compressed_query = (raw_response or "").strip()
            if compressed_query:
                logger.info(
                    f"Thread compress LLM succeeded on attempt {attempt} "
                    f"(model={EMAIL_COMPRESS_LLM_MODEL}, chars={len(compressed_query)})"
                )
                return {
                    "compressed_query": compressed_query,
                    "source": "llm",
                    "model": EMAIL_COMPRESS_LLM_MODEL,
                    "attempts": attempts,
                    "llm_input_preview": llm_input,
                    "error": None,
                }

            last_error = "LLM returned empty content."
            logger.warning(f"Thread compress LLM attempt {attempt} returned empty content.")

        except Exception as exc:
            last_error = str(exc)
            logger.error(
                f"Thread compress LLM attempt {attempt} failed: {exc}",
                exc_info=True,
            )

        if attempt < EMAIL_COMPRESS_MAX_RETRIES:
            await asyncio.sleep(EMAIL_COMPRESS_RETRY_DELAY_SECONDS * attempt)

    fallback_query = build_compressed_query(
        subject=subject,
        latest_inbound=trigger_message,
    )
    logger.warning(
        f"Thread compress LLM failed after {EMAIL_COMPRESS_MAX_RETRIES} attempts; "
        f"using rule-based fallback. Last error: {last_error}"
    )

    return {
        "compressed_query": fallback_query,
        "source": "fallback",
        "model": EMAIL_COMPRESS_LLM_MODEL,
        "attempts": attempts,
        "llm_input_preview": llm_input,
        "error": last_error or "LLM compression failed.",
    }
