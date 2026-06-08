from typing import Any, Dict, List

from services.email_agent_services.email_ai_agent_services import normalize_reply_action
from services.email_agent_services.email_flows.email_flow_constants import (
    DEFAULT_FLOW_EDGE_TYPE,
    DEFAULT_FLOW_LAYOUT_DIRECTION,
    DEFAULT_FLOW_NODE_HEIGHT,
    DEFAULT_FLOW_NODE_ORIGIN,
    DEFAULT_FLOW_NODE_WIDTH,
    DEFAULT_FLOW_ROW_Y,
    DEFAULT_FLOW_SOURCE_HANDLE,
    DEFAULT_FLOW_STEP_X,
    DEFAULT_FLOW_TARGET_HANDLE,
    DEFAULT_GENERATE_EMAIL_FORMAT_PROMPT,
    NODE_TYPE_AI_DEPARTMENT_ROUTER,
    NODE_TYPE_AI_RECIPIENTS_GENERATOR,
    NODE_TYPE_GENERATE_EMAIL,
    NODE_TYPE_LOAD_THREAD_CONTEXT,
    NODE_TYPE_READ_KB,
    NODE_TYPE_READ_TOOLS,
    NODE_TYPE_SAVE_GMAIL_DRAFT,
    NODE_TYPE_SEND_EMAIL,
    NODE_TYPE_START,
    NODE_TYPE_STOP,
    REPLY_ACTION_MODE_AUTO_SEND,
    REPLY_ACTION_MODE_DRAFT,
)

from services.email_agent_services.email_flows.email_flow_validation_services import (
    build_linear_chain,
)

MANDATORY_PIPELINE_NODE_IDS = (
    "start",
    "load_thread_context",
    "generate_email",
    "stop",
)


def _normalize_id_list(values: List[str] | None) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        stripped = str(value).strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        normalized.append(stripped)
    return normalized


def _resolve_tail_node_id(agent: Dict[str, Any]) -> str:
    reply_action = normalize_reply_action(agent.get("reply_action"))
    mode = (reply_action.get("mode") or REPLY_ACTION_MODE_DRAFT).strip().lower()
    if mode == REPLY_ACTION_MODE_AUTO_SEND:
        return "send_email"
    return "save_gmail_draft"


def _resolve_active_node_ids(agent: Dict[str, Any]) -> List[str]:
    knowledge_id = (agent.get("knowledge_id") or "").strip()
    tool_ids = _normalize_id_list(agent.get("tool_ids") or [])
    routing_rule_ids = _normalize_id_list(agent.get("routing_rule_ids") or [])
    recipient_rule_ids = _normalize_id_list(agent.get("recipient_rule_ids") or [])
    tail_node_id = _resolve_tail_node_id(agent)

    node_ids = ["start", "load_thread_context"]
    if knowledge_id:
        node_ids.append("read_kb")
    if tool_ids:
        node_ids.append("read_tools")
    if routing_rule_ids:
        node_ids.append("ai_department_router")
    if recipient_rule_ids:
        node_ids.append("ai_recipients_generator")
    node_ids.extend(["generate_email", tail_node_id, "stop"])
    return node_ids


def _build_node_spec(node_id: str, agent: Dict[str, Any]) -> Dict[str, Any]:
    reply_action = normalize_reply_action(agent.get("reply_action"))
    email_format_template = (agent.get("email_format_template") or "").strip()

    specs: Dict[str, Dict[str, Any]] = {
        "start": {
            "node_id": "start",
            "type": NODE_TYPE_START,
            "label": "Start",
            "config": {},
        },
        "load_thread_context": {
            "node_id": "load_thread_context",
            "type": NODE_TYPE_LOAD_THREAD_CONTEXT,
            "label": "Load Thread Context",
            "config": {},
        },
        "read_kb": {
            "node_id": "read_kb",
            "type": NODE_TYPE_READ_KB,
            "label": "Read KB",
            "config": {
                "limit": 5,
                "knowledge_id": (agent.get("knowledge_id") or "").strip(),
            },
        },
        "read_tools": {
            "node_id": "read_tools",
            "type": NODE_TYPE_READ_TOOLS,
            "label": "Read Tools",
            "config": {
                "max_tool_calls": 3,
                "tool_ids": _normalize_id_list(agent.get("tool_ids") or []),
            },
        },
        "ai_department_router": {
            "node_id": "ai_department_router",
            "type": NODE_TYPE_AI_DEPARTMENT_ROUTER,
            "label": "AI Department Router",
            "config": {
                "routing_rule_ids": _normalize_id_list(agent.get("routing_rule_ids") or []),
            },
        },
        "ai_recipients_generator": {
            "node_id": "ai_recipients_generator",
            "type": NODE_TYPE_AI_RECIPIENTS_GENERATOR,
            "label": "AI Recipients Generator",
            "config": {
                "recipient_rule_ids": _normalize_id_list(agent.get("recipient_rule_ids") or []),
            },
        },
        "generate_email": {
            "node_id": "generate_email",
            "type": NODE_TYPE_GENERATE_EMAIL,
            "label": "Generate Email",
            "config": {
                "llm_model": (agent.get("llm_model") or "").strip(),
                "format_prompt": email_format_template or DEFAULT_GENERATE_EMAIL_FORMAT_PROMPT,
            },
        },
        "save_gmail_draft": {
            "node_id": "save_gmail_draft",
            "type": NODE_TYPE_SAVE_GMAIL_DRAFT,
            "label": "Save Gmail Draft",
            "config": {"reply_action": reply_action},
        },
        "send_email": {
            "node_id": "send_email",
            "type": NODE_TYPE_SEND_EMAIL,
            "label": "Send Email",
            "config": {"reply_action": reply_action},
        },
        "stop": {
            "node_id": "stop",
            "type": NODE_TYPE_STOP,
            "label": "Stop",
            "config": {},
        },
    }
    return specs[node_id]


def get_default_flow_layout() -> Dict[str, Any]:
    """Layout hints for the frontend flow canvas (single horizontal row)."""
    return {
        "direction": DEFAULT_FLOW_LAYOUT_DIRECTION,
        "row_y": DEFAULT_FLOW_ROW_Y,
        "step_x": DEFAULT_FLOW_STEP_X,
        "node_width": DEFAULT_FLOW_NODE_WIDTH,
        "node_height": DEFAULT_FLOW_NODE_HEIGHT,
        "node_origin": list(DEFAULT_FLOW_NODE_ORIGIN),
        "source_handle": DEFAULT_FLOW_SOURCE_HANDLE,
        "target_handle": DEFAULT_FLOW_TARGET_HANDLE,
        "edge_type": DEFAULT_FLOW_EDGE_TYPE,
    }


def _default_node_dimensions() -> Dict[str, int]:
    return {
        "width": DEFAULT_FLOW_NODE_WIDTH,
        "height": DEFAULT_FLOW_NODE_HEIGHT,
    }


def _default_node_position(index: int) -> Dict[str, int]:
    """Place nodes in one horizontal row: x = index * STEP_X, y = ROW_Y."""
    return {
        "x": index * DEFAULT_FLOW_STEP_X,
        "y": DEFAULT_FLOW_ROW_Y,
    }


def relayout_flow_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-apply horizontal row positions and uniform dimensions (fixes legacy stored graphs)."""
    relaid: List[Dict[str, Any]] = []
    for index, node in enumerate(nodes):
        relaid.append({
            **node,
            "position": _default_node_position(index),
            "dimensions": _default_node_dimensions(),
        })
    return relaid


def normalize_stored_flow_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure dimensions exist without overwriting stored positions (editable workflows)."""
    normalized: List[Dict[str, Any]] = []
    for node in nodes:
        normalized.append({
            **node,
            "dimensions": node.get("dimensions") or _default_node_dimensions(),
        })
    return normalized


def nodes_have_overlapping_horizontal_layout(nodes: List[Dict[str, Any]]) -> bool:
    """True when consecutive chain nodes are closer than node width (legacy STEP_X=200 layout)."""
    chain, chain_error = build_linear_chain(nodes)
    if chain_error or not chain or len(chain) < 2:
        return False

    for index in range(1, len(chain)):
        previous_x = (chain[index - 1].get("position") or {}).get("x", 0)
        current_x = (chain[index].get("position") or {}).get("x", 0)
        if current_x - previous_x < DEFAULT_FLOW_NODE_WIDTH:
            return True
    return False


def merge_stored_node_layout(
    new_nodes: List[Dict[str, Any]],
    existing_nodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep canvas position/dimensions from a prior save when syncing graph structure from agent."""
    positions_by_id: Dict[str, Dict[str, int]] = {}
    dimensions_by_id: Dict[str, Dict[str, int]] = {}
    for node in existing_nodes:
        node_id = (node.get("node_id") or "").strip()
        if not node_id:
            continue
        if node.get("position"):
            positions_by_id[node_id] = node["position"]
        if node.get("dimensions"):
            dimensions_by_id[node_id] = node["dimensions"]

    merged: List[Dict[str, Any]] = []
    for node in new_nodes:
        node_id = (node.get("node_id") or "").strip()
        updated = {**node}
        if node_id in positions_by_id:
            updated["position"] = positions_by_id[node_id]
        if node_id in dimensions_by_id:
            updated["dimensions"] = dimensions_by_id[node_id]
        merged.append(updated)
    return merged


def build_minimal_flow_scaffold() -> List[Dict[str, Any]]:
    """Minimal valid workflow: start → load_thread_context → generate_email → save_gmail_draft → stop."""
    node_specs = [
        ("start", NODE_TYPE_START, "Start", {}),
        ("load_thread_context", NODE_TYPE_LOAD_THREAD_CONTEXT, "Load Thread Context", {}),
        ("generate_email", NODE_TYPE_GENERATE_EMAIL, "Generate Email", {
            "llm_model": "",
            "format_prompt": DEFAULT_GENERATE_EMAIL_FORMAT_PROMPT,
        }),
        ("save_gmail_draft", NODE_TYPE_SAVE_GMAIL_DRAFT, "Save Gmail Draft", {
            "reply_action": {"mode": REPLY_ACTION_MODE_DRAFT, "auto_send_min_confidence": 0.8},
        }),
        ("stop", NODE_TYPE_STOP, "Stop", {}),
    ]

    nodes: List[Dict[str, Any]] = []
    for index, (node_id, node_type, label, config) in enumerate(node_specs):
        nodes.append({
            "node_id": node_id,
            "type": node_type,
            "label": label,
            "position": _default_node_position(index),
            "dimensions": _default_node_dimensions(),
            "config": config,
            "edges": [],
        })

    for index in range(len(nodes) - 1):
        nodes[index]["edges"] = [{"to": nodes[index + 1]["node_id"]}]

    return nodes


def build_canvas_edges(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build top-level straight edges for React Flow."""
    edges: List[Dict[str, Any]] = []
    for node in nodes:
        node_id = (node.get("node_id") or "").strip()
        for edge in node.get("edges") or []:
            target = (edge.get("to") or "").strip()
            if not node_id or not target:
                continue
            edges.append({
                "id": f"{node_id}-{target}",
                "source": node_id,
                "target": target,
                "type": DEFAULT_FLOW_EDGE_TYPE,
                "sourceHandle": DEFAULT_FLOW_SOURCE_HANDLE,
                "targetHandle": DEFAULT_FLOW_TARGET_HANDLE,
            })
    return edges


def build_flow_nodes_from_agent(
    agent: Dict[str, Any],
    existing_nodes: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Build the persisted workflow graph for an agent in a clean horizontal row."""
    _ = existing_nodes  # reserved for future custom editable flows
    active_node_ids = _resolve_active_node_ids(agent)
    nodes: List[Dict[str, Any]] = []

    for index, node_id in enumerate(active_node_ids):
        spec = _build_node_spec(node_id, agent)
        nodes.append({
            "node_id": spec["node_id"],
            "type": spec["type"],
            "label": spec["label"],
            "position": _default_node_position(index),
            "dimensions": _default_node_dimensions(),
            "config": spec.get("config", {}),
            "edges": [],
        })

    for index in range(len(nodes) - 1):
        nodes[index]["edges"] = [{"to": nodes[index + 1]["node_id"]}]

    return nodes


def build_flow_summary(agent: Dict[str, Any], node_count: int) -> str:
    reply_action = normalize_reply_action(agent.get("reply_action"))
    mode = reply_action.get("mode", REPLY_ACTION_MODE_DRAFT)
    extras: List[str] = []
    if agent.get("routing_rule_ids"):
        extras.append("routing")
    if agent.get("recipient_rule_ids"):
        extras.append("recipients")

    if mode == REPLY_ACTION_MODE_AUTO_SEND:
        confidence = reply_action.get("auto_send_min_confidence", 0.8)
        mode_label = f"Auto-send when confidence >= {confidence:g}"
    else:
        mode_label = "Draft only"

    summary = f"Inbound reply pipeline · {node_count} nodes · {mode_label}"
    if extras:
        summary = f"{summary} · includes {', '.join(extras)}"
    return summary


def build_default_flow_name(agent_name: str) -> str:
    normalized_name = (agent_name or "Email Agent").strip() or "Email Agent"
    return f"Default — {normalized_name}"
