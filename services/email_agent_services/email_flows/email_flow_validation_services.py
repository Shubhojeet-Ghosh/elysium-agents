from typing import Any, Dict, List, Optional, Set, Tuple

from services.email_agent_services.email_flows.email_flow_constants import (
    NODE_TYPE_AI_DEPARTMENT_ROUTER,
    NODE_TYPE_AI_RECIPIENTS_GENERATOR,
    NODE_TYPE_CALL_EXTERNAL_TOOL,
    NODE_TYPE_GENERATE_EMAIL,
    NODE_TYPE_LOAD_THREAD_CONTEXT,
    NODE_TYPE_READ_KB,
    NODE_TYPE_READ_TOOLS,
    NODE_TYPE_SAVE_GMAIL_DRAFT,
    NODE_TYPE_SEND_EMAIL,
    NODE_TYPE_START,
    NODE_TYPE_STOP,
)

ALLOWED_FLOW_NODE_TYPES = {
    NODE_TYPE_START,
    NODE_TYPE_LOAD_THREAD_CONTEXT,
    NODE_TYPE_READ_KB,
    NODE_TYPE_READ_TOOLS,
    NODE_TYPE_AI_DEPARTMENT_ROUTER,
    NODE_TYPE_AI_RECIPIENTS_GENERATOR,
    NODE_TYPE_GENERATE_EMAIL,
    NODE_TYPE_CALL_EXTERNAL_TOOL,
    NODE_TYPE_SAVE_GMAIL_DRAFT,
    NODE_TYPE_SEND_EMAIL,
    NODE_TYPE_STOP,
}

OPTIONAL_MIDDLE_NODE_TYPES = {
    NODE_TYPE_READ_KB,
    NODE_TYPE_READ_TOOLS,
    NODE_TYPE_AI_DEPARTMENT_ROUTER,
    NODE_TYPE_AI_RECIPIENTS_GENERATOR,
}

TAIL_NODE_TYPES = {
    NODE_TYPE_SAVE_GMAIL_DRAFT,
    NODE_TYPE_SEND_EMAIL,
}


def _validation_error(message: str, *, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "success": False,
        "status_code": 400,
        "message": message,
    }
    if details is not None:
        payload["data"] = details
    return payload


def _node_type(node: Dict[str, Any]) -> str:
    return (node.get("type") or "").strip()


def _node_id(node: Dict[str, Any]) -> str:
    return (node.get("node_id") or "").strip()


def build_linear_chain(nodes: List[Dict[str, Any]]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    """Follow edges from start; fail if graph is not a single linear chain covering all nodes."""
    if not nodes:
        return None, _validation_error("Workflow must include at least one node.")

    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        node_id = _node_id(node)
        if not node_id:
            return None, _validation_error("Every node must have a node_id.")
        if node_id in nodes_by_id:
            return None, _validation_error(f"Duplicate node_id '{node_id}' in workflow.")
        nodes_by_id[node_id] = node

    start_nodes = [node for node in nodes if _node_type(node) == NODE_TYPE_START]
    if len(start_nodes) != 1:
        return None, _validation_error("Workflow must contain exactly one Start node.")

    chain: List[Dict[str, Any]] = [start_nodes[0]]
    visited: Set[str] = {_node_id(start_nodes[0])}
    current = start_nodes[0]

    while True:
        edges = current.get("edges") or []
        if _node_type(current) == NODE_TYPE_STOP:
            if edges:
                return None, _validation_error("Stop node must not have outgoing edges.")
            break

        if not edges:
            return None, _validation_error(
                f"Node '{_node_id(current)}' is missing an outgoing edge.",
            )
        if len(edges) != 1:
            return None, _validation_error(
                f"Node '{_node_id(current)}' must have exactly one outgoing edge.",
            )

        next_id = (edges[0].get("to") or "").strip()
        if not next_id:
            return None, _validation_error(f"Node '{_node_id(current)}' has an empty edge target.")
        if next_id not in nodes_by_id:
            return None, _validation_error(f"Edge target '{next_id}' does not exist in workflow.")
        if next_id in visited:
            return None, _validation_error("Workflow graph contains a cycle.")

        current = nodes_by_id[next_id]
        visited.add(next_id)
        chain.append(current)

    if len(visited) != len(nodes_by_id):
        return None, _validation_error(
            "Workflow must be one connected linear chain (no orphan nodes).",
        )

    return chain, None


def validate_flow_graph(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate workflow structure and ordering rules."""
    for node in nodes:
        node_type = _node_type(node)
        if node_type not in ALLOWED_FLOW_NODE_TYPES:
            return _validation_error(
                f"Node type '{node_type}' is not allowed in a saved workflow.",
            )

    chain, chain_error = build_linear_chain(nodes)
    if chain_error:
        return chain_error
    assert chain is not None

    if _node_type(chain[0]) != NODE_TYPE_START:
        return _validation_error("Workflow must begin with Start.")
    if _node_type(chain[1]) != NODE_TYPE_LOAD_THREAD_CONTEXT:
        return _validation_error(
            "Load Thread Context must be the first node immediately after Start.",
        )
    if _node_type(chain[-1]) != NODE_TYPE_STOP:
        return _validation_error("Workflow must end with Stop.")

    tail_nodes = [node for node in chain if _node_type(node) in TAIL_NODE_TYPES]
    if len(tail_nodes) != 1:
        return _validation_error(
            "Workflow must contain exactly one tail node: Save Gmail Draft or Send Email.",
        )

    tail_node = tail_nodes[0]
    tail_index = chain.index(tail_node)

    external_tool_nodes = [
        node for node in chain if _node_type(node) == NODE_TYPE_CALL_EXTERNAL_TOOL
    ]
    if len(external_tool_nodes) > 1:
        return _validation_error(
            "Workflow may contain at most one Call External Tool node.",
        )

    has_external_tool = bool(external_tool_nodes)
    expected_tail_index = len(chain) - 3 if has_external_tool else len(chain) - 2
    if tail_index != expected_tail_index:
        if has_external_tool:
            return _validation_error(
                "Tail node (Save Gmail Draft or Send Email) must come immediately before "
                "Call External Tool when that node is present.",
            )
        return _validation_error(
            "Tail node (Save Gmail Draft or Send Email) must come immediately before Stop.",
        )

    generate_nodes = [node for node in chain if _node_type(node) == NODE_TYPE_GENERATE_EMAIL]
    if len(generate_nodes) != 1:
        return _validation_error("Workflow must contain exactly one Generate Email node.")

    generate_index = chain.index(generate_nodes[0])
    if generate_index >= tail_index:
        return _validation_error(
            "Generate Email must appear before the tail node (Save Gmail Draft or Send Email).",
        )

    if external_tool_nodes:
        external_node = external_tool_nodes[0]
        external_index = chain.index(external_node)
        if external_index != len(chain) - 2:
            return _validation_error(
                "Call External Tool must be the last node immediately before Stop.",
            )
        if external_index <= tail_index:
            return _validation_error(
                "Call External Tool must appear after the tail node "
                "(Save Gmail Draft or Send Email).",
            )

    middle_nodes = chain[2:generate_index]
    for node in middle_nodes:
        if _node_type(node) not in OPTIONAL_MIDDLE_NODE_TYPES:
            return _validation_error(
                f"Invalid node '{_node_id(node)}' between Load Thread Context and Generate Email. "
                f"Allowed optional nodes: Read KB, Read Tools, AI Department Router, "
                f"AI Recipients Generator.",
            )

    return None


def resolve_external_tool_ids_from_config(config: Dict[str, Any]) -> List[str]:
    """
    Resolve tool ids for Call External Tool node config.

    Canonical key is external_tools[]. Accepts legacy tool_ids[] (e.g. frontend
    reusing the Read Tools picker field name) until the canvas serializes external_tools.
    """
    raw_ids = config.get("external_tools")
    if not raw_ids:
        raw_ids = config.get("tool_ids") or []
    return [str(tool_id).strip() for tool_id in raw_ids if str(tool_id).strip()]


def normalize_call_external_tool_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Persist canonical external_tools[] and drop mistaken tool_ids[] on save."""
    normalized: List[Dict[str, Any]] = []
    for node in nodes:
        if _node_type(node) != NODE_TYPE_CALL_EXTERNAL_TOOL:
            normalized.append(node)
            continue

        config = dict(node.get("config") or {})
        external_tool_ids = resolve_external_tool_ids_from_config(config)
        config["external_tools"] = external_tool_ids
        config.pop("tool_ids", None)
        normalized.append({**node, "config": config})
    return normalized


def extract_call_external_tool_config(nodes: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Return the Call External Tool node config when present in a saved workflow."""
    for node in nodes:
        if _node_type(node) == NODE_TYPE_CALL_EXTERNAL_TOOL:
            config = dict(node.get("config") or {})
            external_tool_ids = resolve_external_tool_ids_from_config(config)
            return {
                **config,
                "external_tools": external_tool_ids,
            }
    return None
