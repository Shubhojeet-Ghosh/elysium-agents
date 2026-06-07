from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_TYPE_GENERATE_EMAIL,
)
from services.email_agent_services.email_flows.email_generate_llm_services import (
    generate_email_with_llm,
)

logger = get_logger()

NODE_ID = "generate_email"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _set_draft_context_defaults(context: Dict[str, Any]) -> None:
    context["draft"] = {
        "subject": "",
        "body_text": "",
        "body_html": "",
        "confidence": 0.0,
        "decision_source": "",
        "reason": "",
    }


def _apply_generation_result(context: Dict[str, Any], result: Dict[str, Any]) -> None:
    context["draft"] = {
        "subject": result.get("subject", "") or "",
        "body_text": result.get("body_text", "") or "",
        "body_html": result.get("body_html", "") or "",
        "confidence": result.get("confidence", 0.0),
        "decision_source": result.get("decision_source", "") or "",
        "reason": result.get("reason", "") or "",
    }


async def execute_generate_email_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Generate the reply email draft using thread, KB, tools, prompts, and template.

    Writes context.draft including confidence for downstream send/draft tail nodes.
    """
    started_at = _utc_now()
    llm_model = (agent.get("llm_model") or "").strip()
    thread_id = (context.get("thread_id") or "").strip()
    system_prompt = (context.get("system_prompt") or agent.get("system_prompt") or "").strip()
    thread_messages = (context.get("thread") or {}).get("messages") or []
    recipients = context.get("recipients") or {}

    input_summary = {
        "llm_model": llm_model,
        "thread_id": thread_id,
        "thread_message_count": len(thread_messages),
        "kb_chunk_count": len(context.get("kb_chunks") or []),
        "tool_result_count": len(context.get("tool_results") or []),
        "has_email_format_template": bool((context.get("email_format_template") or "").strip()),
        "reply_to": (recipients.get("to") or [""])[0] if recipients.get("to") else "",
        "thread_subject": ((context.get("thread") or {}).get("subject") or "").strip(),
    }

    logger.info(
        f"generate_email_node started thread_id={thread_id} llm_model={llm_model}"
    )

    try:
        if not system_prompt:
            raise ValueError("system_prompt is required for Generate Email.")
        if not llm_model:
            raise ValueError("agent.llm_model is required for Generate Email.")
        if not thread_messages:
            raise ValueError("thread.messages is required for Generate Email.")

        generation_result = await generate_email_with_llm(
            context=context,
            llm_model=llm_model,
        )
        _apply_generation_result(context, generation_result)

        decision_source = generation_result.get("decision_source", "")
        confidence = generation_result.get("confidence", 0.0)
        llm_prompt_text = generation_result.get("llm_prompt_text", "") or ""

        logger.info(
            f"generate_email_node completed thread_id={thread_id} "
            f"decision_source={decision_source} confidence={confidence} "
            f"draft_chars={len(context['draft'].get('body_text', ''))}"
        )

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_GENERATE_EMAIL,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "draft": context["draft"],
                "decision_source": decision_source,
                "llm_model": generation_result.get("llm_model", ""),
                "llm_attempts": generation_result.get("attempts", 0),
                "llm_prompt_text": llm_prompt_text,
                "llm_raw_response_preview": (generation_result.get("llm_raw_response") or "")[:500],
                "draft_preview": (context["draft"].get("body_text") or "")[:500],
                "context": context,
                "downstream_hints": {
                    "call_external_tool": {
                        "uses": ["draft"],
                    },
                    "save_gmail_draft": {
                        "uses": ["draft", "recipients"],
                    },
                    "send_email": {
                        "uses": ["draft", "recipients", "agent.reply_action"],
                    },
                },
            },
            "error": generation_result.get("error"),
        }
        return context, node_log

    except Exception as exc:
        logger.error(
            f"generate_email_node failed thread_id={thread_id}: {exc}",
            exc_info=True,
        )
        _set_draft_context_defaults(context)
        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        context.setdefault("errors", []).append({
            "node_id": NODE_ID,
            "message": str(exc),
        })

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_GENERATE_EMAIL,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
