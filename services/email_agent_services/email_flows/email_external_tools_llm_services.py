from typing import Any, Dict, List

from services.email_agent_services.email_flows.email_department_router_llm_services import (
    format_thread_messages_for_routing,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_ROUTER_MESSAGE_LIMIT,
    EMAIL_TOOLS_DEFAULT_MAX_CALLS,
)
from services.email_agent_services.email_flows.email_read_tools_llm_services import (
    execute_planned_email_tools,
    plan_email_tools_with_llm,
    summarize_registered_tools,
)

EMAIL_EXTERNAL_TOOLS_PLANNING_SYSTEM_PROMPT = """You are a post-reply action assistant for an email support agent.

Your only job is to decide whether any registered external tool should be called now as a side effect after the reply has been drafted (for example: create a CRM record, update a ticket, log an event).

Rules:
- Read each tool's description and parameter descriptions carefully — they define when and how to call the tool.
- Give the most weight to the trigger / latest inbound customer message in the thread context.
- Only call a tool when its description clearly applies to what happened in this thread and the drafted reply.
- Do not call a tool if required arguments are missing from the thread (for example, no ticket number when the tool needs one).
- If no tool is appropriate, do not call any tool.
- Use exact argument values from the thread without inventing IDs, numbers, or other data.
- Do not draft or rewrite the email — only decide on post-reply tool calls."""


def _format_thread_subject(context: Dict[str, Any]) -> str:
    thread = context.get("thread") or {}
    return (thread.get("subject") or "").strip()


def _format_draft_preview(context: Dict[str, Any]) -> str:
    draft = context.get("draft") or {}
    subject = (draft.get("subject") or "").strip()
    body_text = (draft.get("body_text") or "").strip()
    confidence = draft.get("confidence")
    lines = [
        f"Subject: {subject or '(unknown)'}",
        f"Confidence: {confidence if confidence is not None else '(unknown)'}",
        "Body:",
        body_text or "(empty)",
    ]
    return "\n".join(lines)


def build_external_tools_llm_user_message(*, context: Dict[str, Any]) -> str:
    """Build LLM user message for post-draft external tool planning."""
    compressed_query = (context.get("compressed_query") or "").strip()
    thread = context.get("thread") or {}
    messages = thread.get("messages") or []

    lines = [
        f"Email subject: {_format_thread_subject(context) or '(unknown)'}",
        "",
        "Compressed thread context:",
        compressed_query or "(empty)",
        "",
        f"Recent thread emails (last {EMAIL_ROUTER_MESSAGE_LIMIT}, trigger message emphasized):",
        format_thread_messages_for_routing(
            messages,
            limit=EMAIL_ROUTER_MESSAGE_LIMIT,
        ),
        "",
        "Drafted reply (already generated — for context only):",
        _format_draft_preview(context),
        "",
        "Decide whether any registered external tool should be called now as a post-reply side effect.",
    ]
    return "\n".join(lines)


async def plan_and_execute_external_tools(
    *,
    context: Dict[str, Any],
    tools: List[Dict[str, Any]],
    llm_model: str,
    max_tool_calls: int = EMAIL_TOOLS_DEFAULT_MAX_CALLS,
) -> Dict[str, Any]:
    """Full Call External Tool pipeline: LLM decides tool calls, then HTTP executes them."""
    user_message = build_external_tools_llm_user_message(context=context)

    planning_result = await plan_email_tools_with_llm(
        context=context,
        tools=tools,
        llm_model=llm_model,
        system_prompt=EMAIL_EXTERNAL_TOOLS_PLANNING_SYSTEM_PROMPT,
        user_message=user_message,
    )

    tool_calls = planning_result.get("tool_calls") or []
    llm_decision = "called" if tool_calls else "no_call"

    execution_result = await execute_planned_email_tools(
        tool_calls=tool_calls,
        tools=tools,
        max_tool_calls=max_tool_calls,
    )

    registered_tools = planning_result.get("registered_tools") or summarize_registered_tools(tools)

    return {
        "registered_tools": registered_tools,
        "tools_registered": True,
        "tools_registered_count": len(registered_tools),
        "llm_decision": llm_decision,
        "tools_planned": execution_result.get("tools_planned") or [],
        "tool_results": execution_result.get("tool_results") or [],
        "tool_executions": execution_result.get("tool_executions") or [],
        "llm_content": planning_result.get("content", "") or "",
        "model": planning_result.get("model", ""),
        "attempts": planning_result.get("attempts", 0),
        "tool_calls_requested": len(tool_calls),
        "tool_calls_executed": len(execution_result.get("tool_results") or []),
    }
