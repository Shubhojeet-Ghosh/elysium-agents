from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_external_tools_llm_services import (
    plan_and_execute_external_tools,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_TOOLS_DEFAULT_MAX_CALLS,
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_LOG_STATUS_SKIPPED,
    NODE_TYPE_CALL_EXTERNAL_TOOL,
)
from services.email_agent_services.email_flows.email_read_tools_llm_services import (
    summarize_registered_tools,
)
from services.email_agent_services.email_flows.email_flow_validation_services import (
    resolve_external_tool_ids_from_config,
)
from services.email_agent_services.email_tool_definitions.email_tool_definitions_mongo_services import (
    get_tools_by_ids,
)

logger = get_logger()

NODE_ID = "call_external_tool"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_external_tool_ids(config: Dict[str, Any]) -> List[str]:
    return resolve_external_tool_ids_from_config(config)


async def _load_active_tools(
    *,
    tool_ids: List[str],
    team_id: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    tools_map = await get_tools_by_ids(tool_ids)

    active_tools: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for tool_id in tool_ids:
        tool = tools_map.get(tool_id)
        if not tool:
            warnings.append(f"Tool id '{tool_id}' not found.")
            continue
        if (tool.get("status") or "").strip().lower() != "active":
            warnings.append(f"Tool '{tool.get('name', tool_id)}' is not active.")
            continue
        if (tool.get("team_id") or "").strip() != team_id.strip():
            warnings.append(f"Tool '{tool.get('name', tool_id)}' does not belong to team.")
            continue
        active_tools.append(tool)

    return active_tools, warnings


def _set_external_tool_context_defaults(context: Dict[str, Any]) -> None:
    context["external_tools_registered"] = []
    context["external_tools_planned"] = []
    context["external_tool_results"] = []


def _build_skip_output(
    *,
    context: Dict[str, Any],
    skip_reason: str,
    tools_registered: bool,
    configured_tool_ids: List[str],
    registered_tools: List[Dict[str, Any]] | None = None,
    warnings: List[str] | None = None,
) -> Dict[str, Any]:
    return {
        "tools_registered": tools_registered,
        "configured_external_tools": configured_tool_ids,
        "registered_tools": registered_tools or [],
        "tools_registered_count": len(registered_tools or []),
        "llm_decision": "skipped",
        "skip_reason": skip_reason,
        "tool_calls_requested": 0,
        "tool_calls_executed": 0,
        "tools_planned": [],
        "tool_results": [],
        "tool_executions": [],
        "warnings": warnings or [],
        "context": context,
    }


async def execute_call_external_tool_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    LLM tool planning + HTTP execution for flow-configured post-draft external tools.

    Writes context.external_tools_registered, context.external_tools_planned,
    context.external_tool_results. Flow-only — not synced to agent.tool_ids.
    """
    started_at = _utc_now()
    external_tool_ids = _resolve_external_tool_ids(config)
    team_id = (context.get("team_id") or agent.get("team_id") or "").strip()
    thread_id = (context.get("thread_id") or "").strip()
    llm_model = (agent.get("llm_model") or "").strip()
    max_tool_calls = int(config.get("max_tool_calls") or EMAIL_TOOLS_DEFAULT_MAX_CALLS)

    input_summary = {
        "external_tools": external_tool_ids,
        "tool_count": len(external_tool_ids),
        "llm_model": llm_model,
        "max_tool_calls": max_tool_calls,
        "compressed_query_length": len((context.get("compressed_query") or "").strip()),
        "has_draft": bool(context.get("draft")),
    }

    logger.info(
        f"call_external_tool_node started thread_id={thread_id} "
        f"external_tools={external_tool_ids} llm_model={llm_model}"
    )

    try:
        if not external_tool_ids:
            _set_external_tool_context_defaults(context)
            logger.info(
                f"call_external_tool_node skipped thread_id={thread_id} — "
                f"no external_tools configured on flow node"
            )
            completed_at = _utc_now()
            node_log = {
                "node_id": NODE_ID,
                "node_type": NODE_TYPE_CALL_EXTERNAL_TOOL,
                "status": NODE_LOG_STATUS_SKIPPED,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
                "input_summary": input_summary,
                "output": _build_skip_output(
                    context=context,
                    skip_reason="No external_tools configured on flow node.",
                    tools_registered=False,
                    configured_tool_ids=[],
                ),
                "error": None,
            }
            return context, node_log

        active_tools, load_warnings = await _load_active_tools(
            tool_ids=external_tool_ids,
            team_id=team_id,
        )
        registered_tools = summarize_registered_tools(active_tools)

        if not active_tools:
            _set_external_tool_context_defaults(context)
            logger.warning(
                f"call_external_tool_node skipped thread_id={thread_id} — "
                f"configured external_tools={external_tool_ids} but no active tools resolved. "
                f"warnings={load_warnings}"
            )
            completed_at = _utc_now()
            node_log = {
                "node_id": NODE_ID,
                "node_type": NODE_TYPE_CALL_EXTERNAL_TOOL,
                "status": NODE_LOG_STATUS_SKIPPED,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
                "input_summary": input_summary,
                "output": _build_skip_output(
                    context=context,
                    skip_reason="No active tools resolved for configured external_tools.",
                    tools_registered=True,
                    configured_tool_ids=external_tool_ids,
                    registered_tools=[],
                    warnings=load_warnings,
                ),
                "error": None,
            }
            return context, node_log

        logger.info(
            f"call_external_tool_node loaded {len(active_tools)} active tool(s) "
            f"for thread_id={thread_id}: "
            f"{[tool['tool_name'] for tool in registered_tools]}"
        )

        result = await plan_and_execute_external_tools(
            context=context,
            tools=active_tools,
            llm_model=llm_model,
            max_tool_calls=max_tool_calls,
        )

        registered_tools = result.get("registered_tools") or registered_tools
        tools_planned = result.get("tools_planned") or []
        tool_results = result.get("tool_results") or []
        tool_executions = result.get("tool_executions") or []
        llm_decision = result.get("llm_decision", "no_call")

        context["external_tools_registered"] = registered_tools
        context["external_tools_planned"] = tools_planned
        context["external_tool_results"] = tool_results

        if llm_decision == "called":
            logger.info(
                f"call_external_tool_node finished thread_id={thread_id} — LLM called "
                f"{len(tool_executions)} tool(s)"
            )
            for execution in tool_executions:
                logger.info(
                    "call_external_tool_node tool execution: "
                    f"id={execution.get('tool_id')} "
                    f"name={execution.get('tool_name')} "
                    f"success={execution.get('success')} "
                    f"message={execution.get('message')}"
                )
        else:
            logger.info(
                f"call_external_tool_node finished thread_id={thread_id} — "
                f"{len(registered_tools)} tool(s) registered but LLM decided no call needed"
            )

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_CALL_EXTERNAL_TOOL,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "tools_registered": True,
                "configured_external_tools": external_tool_ids,
                "registered_tools": registered_tools,
                "tools_registered_count": len(registered_tools),
                "llm_decision": llm_decision,
                "llm_model": result.get("model", ""),
                "llm_attempts": result.get("attempts", 0),
                "tool_calls_requested": result.get("tool_calls_requested", 0),
                "tool_calls_executed": result.get("tool_calls_executed", 0),
                "tools_planned": tools_planned,
                "tool_results": tool_results,
                "tool_executions": tool_executions,
                "warnings": load_warnings,
                "context": context,
            },
            "error": None,
        }
        return context, node_log

    except Exception as exc:
        logger.error(
            f"call_external_tool_node failed thread_id={thread_id} "
            f"external_tools={external_tool_ids}: {exc}",
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
            "node_type": NODE_TYPE_CALL_EXTERNAL_TOOL,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
