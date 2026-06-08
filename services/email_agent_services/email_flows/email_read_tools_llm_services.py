import asyncio
from typing import Any, Dict, List

from config.llm_models_config import resolve_model_handler
from logging_config import get_logger
from services.email_agent_services.email_external_tools.email_tool_http_executor_services import (
    execute_email_tool_http_call,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_FLOW_REASONING_LLM_MODELS,
    EMAIL_TOOLS_LLM_MAX_RETRIES,
    EMAIL_TOOLS_LLM_RETRY_DELAY_SECONDS,
)
from services.email_agent_services.email_tool_definitions.email_tool_schema_builder import (
    build_llm_tool_definition,
)
from services.open_ai_services import openai_chat_completion_with_tools

logger = get_logger()

EMAIL_TOOLS_PLANNING_SYSTEM_PROMPT = """You are a tool-routing assistant for an email support agent.

Your only job is to decide whether any registered external tool should be called now to gather factual data before a reply is drafted.

Rules:
- Read each tool's description and parameter descriptions carefully — they define when and how to call the tool.
- Only call a tool when its description clearly applies to the customer's request in the thread context.
- Do not call a tool if required arguments are missing from the thread (for example, no ticket number when the tool needs one).
- If no tool is appropriate, do not call any tool.
- Use exact argument values from the thread without inventing IDs, numbers, or other data.
- Do not draft an email reply — only decide on tool calls."""


def _format_kb_snippets(kb_chunks: List[Dict[str, Any]]) -> str:
    if not kb_chunks:
        return "(none)"

    lines: List[str] = []
    for index, chunk in enumerate(kb_chunks, start=1):
        text_content = (chunk.get("text_content") or "").strip()
        if not text_content:
            continue
        lines.append(f"[{index}] {text_content}")

    return "\n".join(lines) if lines else "(none)"


def _format_thread_subject(context: Dict[str, Any]) -> str:
    thread = context.get("thread") or {}
    return (thread.get("subject") or "").strip()


def build_tools_llm_user_message(*, context: Dict[str, Any]) -> str:
    compressed_query = (context.get("compressed_query") or "").strip()
    kb_title = (context.get("kb_title") or "").strip()
    kb_chunks = context.get("kb_chunks") or []

    lines = [
        f"Email subject: {_format_thread_subject(context) or '(unknown)'}",
        "",
        "Compressed thread context:",
        compressed_query or "(empty)",
        "",
        f"Knowledge base: {kb_title or '(none)'}",
        "Knowledge snippets:",
        _format_kb_snippets(kb_chunks),
        "",
        "Decide whether any registered tool should be called now to gather facts for the reply.",
    ]
    return "\n".join(lines)


def _get_tool_id(tool: Dict[str, Any]) -> str:
    raw_id = tool.get("_id", tool.get("tool_id", ""))
    return str(raw_id) if raw_id else ""


def summarize_registered_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compact registry snapshot for context, logs, and downstream LLM prompts."""
    summarized: List[Dict[str, Any]] = []
    for tool in tools:
        summarized.append({
            "tool_id": _get_tool_id(tool),
            "tool_name": (tool.get("name") or "").strip(),
            "display_name": (tool.get("display_name") or "").strip(),
            "status": (tool.get("status") or "").strip(),
        })
    return summarized


def _resolve_api_success(
    *,
    http_success: bool,
    response_body: Any,
) -> bool:
    if isinstance(response_body, dict) and "success" in response_body:
        return bool(response_body.get("success"))
    return http_success


def _build_tool_result_entry(
    *,
    tool_doc: Dict[str, Any] | None,
    tool_name: str,
    arguments: Dict[str, Any],
    http_result: Dict[str, Any],
) -> Dict[str, Any]:
    response_body = http_result.get("response")
    http_success = bool(http_result.get("success", False))
    api_success = _resolve_api_success(
        http_success=http_success,
        response_body=response_body,
    )

    message = (http_result.get("message") or "").strip()
    if isinstance(response_body, dict) and response_body.get("message"):
        message = str(response_body.get("message"))

    entry: Dict[str, Any] = {
        "tool_id": _get_tool_id(tool_doc) if tool_doc else "",
        "tool_name": tool_name,
        "display_name": (tool_doc.get("display_name") or "").strip() if tool_doc else "",
        "arguments": arguments,
        "called": True,
        "success": api_success,
        "http_success": http_success,
        "status_code": http_result.get("status_code"),
        "message": message,
        "response": response_body,
    }
    return entry


def _build_tools_by_name(tools: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    tools_by_name: Dict[str, Dict[str, Any]] = {}
    for tool in tools:
        name = (tool.get("name") or "").strip().lower()
        if name:
            tools_by_name[name] = tool
    return tools_by_name


def _validate_llm_model(llm_model: str) -> str:
    normalized = (llm_model or "").strip()
    if not normalized:
        raise ValueError("agent.llm_model is required for Read Tools.")

    if normalized not in EMAIL_FLOW_REASONING_LLM_MODELS:
        allowed = ", ".join(sorted(EMAIL_FLOW_REASONING_LLM_MODELS))
        raise ValueError(
            f"Unsupported llm_model '{normalized}' for Read Tools. "
            f"Allowed models for this prototype: {allowed}."
        )

    _, model_config = resolve_model_handler(normalized)
    if model_config.get("mode") != "reasoning":
        raise ValueError(
            f"llm_model '{normalized}' must be a reasoning model for tool calling."
        )

    return normalized


async def plan_email_tools_with_llm(
    *,
    context: Dict[str, Any],
    tools: List[Dict[str, Any]],
    llm_model: str,
    system_prompt: str | None = None,
    user_message: str | None = None,
) -> Dict[str, Any]:
    """
    Ask the agent's reasoning LLM whether to call any registered tools.

    Uses a fixed tool-planning system prompt — not the agent's reply system_prompt.
    Returns tool_calls list (may be empty) plus optional assistant content.
    """
    validated_model = _validate_llm_model(llm_model)
    compressed_query = (context.get("compressed_query") or "").strip()

    if not compressed_query:
        raise ValueError(
            "compressed_query is empty — Load Thread Context must run first."
        )

    if not tools:
        return {
            "tool_calls": [],
            "content": "",
            "model": validated_model,
            "attempts": 0,
            "error": None,
        }

    llm_tools = [build_llm_tool_definition(tool) for tool in tools]
    registered_summary = summarize_registered_tools(tools)
    planning_label = "External Tools" if system_prompt else "Read Tools"
    logger.info(
        f"{planning_label} LLM planning started "
        f"(model={validated_model}, registered_tools={len(registered_summary)})"
    )
    for registered_tool in registered_summary:
        logger.info(
            f"{planning_label} registered tool: "
            f"id={registered_tool['tool_id']} "
            f"name={registered_tool['tool_name']} "
            f"display={registered_tool['display_name']}"
        )

    messages = [
        {
            "role": "system",
            "content": system_prompt or EMAIL_TOOLS_PLANNING_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_message or build_tools_llm_user_message(context=context),
        },
    ]

    last_error = ""
    attempts = 0

    for attempt in range(1, EMAIL_TOOLS_LLM_MAX_RETRIES + 1):
        attempts = attempt
        try:
            completion = await openai_chat_completion_with_tools({
                "model": validated_model,
                "messages": messages,
                "tools": llm_tools,
                "tool_choice": "auto",
            })

            tool_calls = completion.get("tool_calls") or []
            if tool_calls:
                planned_names = [
                    (call.get("name") or "").strip()
                    for call in tool_calls
                ]
                logger.info(
                    f"Read Tools LLM planning succeeded on attempt {attempt} "
                    f"(model={validated_model}, tool_calls={len(tool_calls)}, "
                    f"tools={planned_names})"
                )
            else:
                logger.info(
                    f"Read Tools LLM planning succeeded on attempt {attempt} "
                    f"(model={validated_model}, tool_calls=0 — LLM decided no tool needed)"
                )
            return {
                "tool_calls": tool_calls,
                "content": completion.get("content", "") or "",
                "model": validated_model,
                "attempts": attempts,
                "registered_tools": registered_summary,
                "error": None,
            }

        except Exception as exc:
            last_error = str(exc)
            logger.error(
                f"Read Tools LLM planning attempt {attempt} failed: {exc}",
                exc_info=True,
            )

        if attempt < EMAIL_TOOLS_LLM_MAX_RETRIES:
            await asyncio.sleep(EMAIL_TOOLS_LLM_RETRY_DELAY_SECONDS * attempt)

    raise ValueError(
        last_error or "LLM tool planning failed after all retries."
    )


async def execute_planned_email_tools(
    *,
    tool_calls: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    max_tool_calls: int,
) -> Dict[str, Any]:
    """Execute LLM-planned tool calls via each tool's HTTP endpoint."""
    tools_by_name = _build_tools_by_name(tools)
    tools_planned: List[Dict[str, Any]] = []
    tool_results: List[Dict[str, Any]] = []

    if not tool_calls:
        logger.info("Read Tools execution skipped — LLM planned zero tool calls.")
        return {
            "tools_planned": [],
            "tool_results": [],
            "tool_executions": [],
        }

    logger.info(
        f"Read Tools executing {min(len(tool_calls), max_tool_calls)} planned tool call(s)"
    )

    for tool_call in tool_calls[:max_tool_calls]:
        tool_name = (tool_call.get("name") or "").strip().lower()
        arguments = tool_call.get("arguments") or {}
        tool_call_id = tool_call.get("id", "")

        tool_doc = tools_by_name.get(tool_name)
        tool_id = _get_tool_id(tool_doc) if tool_doc else ""

        planned_entry = {
            "tool_call_id": tool_call_id,
            "tool_id": tool_id,
            "tool_name": tool_name,
            "display_name": (tool_doc.get("display_name") or "").strip() if tool_doc else "",
            "arguments": arguments,
        }
        tools_planned.append(planned_entry)

        if not tool_doc:
            logger.warning(
                f"Read Tools planned unknown tool '{tool_name}' — not in registered tools"
            )
            tool_results.append({
                "tool_id": "",
                "tool_name": tool_name,
                "display_name": "",
                "arguments": arguments,
                "called": True,
                "success": False,
                "http_success": False,
                "status_code": 404,
                "message": f"Tool '{tool_name}' is not registered on this agent.",
                "response": None,
            })
            continue

        logger.info(
            f"Read Tools HTTP call starting: tool_id={tool_id} "
            f"name={tool_name} arguments={arguments}"
        )

        http_result = await execute_email_tool_http_call(
            endpoint_url=tool_doc.get("endpoint_url", ""),
            http_method=tool_doc.get("http_method", "POST"),
            arguments=arguments,
        )

        tool_result = _build_tool_result_entry(
            tool_doc=tool_doc,
            tool_name=tool_name,
            arguments=arguments,
            http_result=http_result,
        )
        tool_results.append(tool_result)

        logger.info(
            f"Read Tools HTTP call finished: tool_id={tool_id} name={tool_name} "
            f"success={tool_result.get('success')} status_code={tool_result.get('status_code')} "
            f"message={tool_result.get('message')}"
        )

    tool_executions = [
        {
            "tool_id": result.get("tool_id", ""),
            "tool_name": result.get("tool_name", ""),
            "display_name": result.get("display_name", ""),
            "arguments": result.get("arguments", {}),
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "response": result.get("response"),
        }
        for result in tool_results
    ]

    return {
        "tools_planned": tools_planned,
        "tool_results": tool_results,
        "tool_executions": tool_executions,
    }


async def plan_and_execute_email_tools(
    *,
    context: Dict[str, Any],
    tools: List[Dict[str, Any]],
    llm_model: str,
    max_tool_calls: int,
) -> Dict[str, Any]:
    """
    Full Read Tools pipeline: LLM decides tool calls, then HTTP executes them.
    """
    registered_tools = summarize_registered_tools(tools)

    planning_result = await plan_email_tools_with_llm(
        context=context,
        tools=tools,
        llm_model=llm_model,
    )

    tool_calls = planning_result.get("tool_calls") or []
    llm_decision = "called" if tool_calls else "no_call"

    execution_result = await execute_planned_email_tools(
        tool_calls=tool_calls,
        tools=tools,
        max_tool_calls=max_tool_calls,
    )

    return {
        "registered_tools": planning_result.get("registered_tools") or registered_tools,
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
