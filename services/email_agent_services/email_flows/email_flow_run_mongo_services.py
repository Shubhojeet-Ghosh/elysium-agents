from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_FLOW_RUNS_COLLECTION,
    FLOW_RUN_STATUS_COMPLETED,
    FLOW_RUN_STATUS_FAILED,
    FLOW_RUN_STATUS_QUEUED,
    FLOW_RUN_STATUS_RUNNING,
    FLOW_RUN_STATUS_SKIPPED,
)
from services.email_agent_services.email_flows.email_flow_context import (
    serialize_for_json,
)
from services.mongo_services import get_collection


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_run_id() -> str:
    return str(uuid4())


def _serialize_node_logs(node_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for entry in node_logs:
        serialized.append(serialize_for_json({
            "node_id": entry.get("node_id", ""),
            "node_type": entry.get("node_type", ""),
            "status": entry.get("status", ""),
            "started_at": entry.get("started_at"),
            "completed_at": entry.get("completed_at"),
            "duration_ms": entry.get("duration_ms"),
            "input_summary": entry.get("input_summary", {}),
            "output": entry.get("output", {}),
            "error": entry.get("error"),
        }))
    return serialized


def serialize_flow_run(run_doc: Dict[str, Any]) -> Dict[str, Any]:
    return serialize_for_json({
        "run_id": run_doc.get("run_id", ""),
        "agent_id": run_doc.get("agent_id", ""),
        "team_id": run_doc.get("team_id", ""),
        "thread_id": run_doc.get("thread_id", ""),
        "trigger_message_id": run_doc.get("trigger_message_id", ""),
        "status": run_doc.get("status", ""),
        "current_node_id": run_doc.get("current_node_id", ""),
        "preview": run_doc.get("preview", False),
        "run_type": run_doc.get("run_type", ""),
        "context": run_doc.get("context", {}),
        "node_logs": _serialize_node_logs(run_doc.get("node_logs", [])),
        "error": run_doc.get("error"),
        "started_at": run_doc.get("started_at"),
        "completed_at": run_doc.get("completed_at"),
        "created_at": run_doc.get("created_at"),
        "updated_at": run_doc.get("updated_at"),
    })


async def create_flow_run(
    *,
    agent_id: str,
    team_id: str,
    thread_id: str,
    trigger_message_id: str,
    context: Dict[str, Any],
    run_id: str = "",
    preview: bool = False,
    run_type: str = "reprocess",
    status: str = FLOW_RUN_STATUS_RUNNING,
) -> Dict[str, Any]:
    now = _utc_now()
    normalized_run_id = (run_id or generate_run_id()).strip()
    document = {
        "run_id": normalized_run_id,
        "agent_id": agent_id.strip(),
        "team_id": team_id.strip(),
        "thread_id": thread_id.strip(),
        "trigger_message_id": trigger_message_id.strip(),
        "status": status,
        "current_node_id": "",
        "context": context,
        "node_logs": [],
        "error": None,
        "preview": preview,
        "run_type": run_type,
        "started_at": now,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }

    collection = get_collection(EMAIL_FLOW_RUNS_COLLECTION)
    await collection.insert_one(document)
    return document


async def get_flow_run_by_id(run_id: str) -> Optional[Dict[str, Any]]:
    collection = get_collection(EMAIL_FLOW_RUNS_COLLECTION)
    return await collection.find_one({"run_id": run_id.strip()})


async def append_flow_node_log(
    run_id: str,
    *,
    node_id: str,
    node_type: str,
    status: str,
    started_at: datetime,
    completed_at: datetime,
    duration_ms: int,
    input_summary: Dict[str, Any],
    output: Dict[str, Any],
    error: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    log_entry = {
        "node_id": node_id,
        "node_type": node_type,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "input_summary": input_summary,
        "output": output,
        "error": error,
    }

    collection = get_collection(EMAIL_FLOW_RUNS_COLLECTION)
    await collection.update_one(
        {"run_id": run_id.strip()},
        {
            "$push": {"node_logs": log_entry},
            "$set": {
                "current_node_id": node_id,
                "context": context if context is not None else output.get("context", {}),
                "updated_at": _utc_now(),
            },
        },
    )


async def update_flow_run_trigger_message(run_id: str, trigger_message_id: str) -> None:
    collection = get_collection(EMAIL_FLOW_RUNS_COLLECTION)
    await collection.update_one(
        {"run_id": run_id.strip()},
        {
            "$set": {
                "trigger_message_id": trigger_message_id.strip(),
                "updated_at": _utc_now(),
            },
        },
    )


async def update_flow_run_context(
    run_id: str,
    *,
    context: Dict[str, Any],
    current_node_id: str = "",
    status: str = "",
) -> None:
    update_fields: Dict[str, Any] = {
        "context": context,
        "updated_at": _utc_now(),
    }
    if current_node_id:
        update_fields["current_node_id"] = current_node_id
    if status:
        update_fields["status"] = status
        if status in {
            FLOW_RUN_STATUS_COMPLETED,
            FLOW_RUN_STATUS_FAILED,
            FLOW_RUN_STATUS_SKIPPED,
        }:
            update_fields["completed_at"] = _utc_now()

    collection = get_collection(EMAIL_FLOW_RUNS_COLLECTION)
    await collection.update_one(
        {"run_id": run_id.strip()},
        {"$set": update_fields},
    )


async def update_flow_run_status(
    run_id: str,
    *,
    status: str,
    error: Optional[str] = None,
) -> None:
    update_fields: Dict[str, Any] = {
        "status": status,
        "updated_at": _utc_now(),
    }
    if error is not None:
        update_fields["error"] = error
    if status in {
        FLOW_RUN_STATUS_COMPLETED,
        FLOW_RUN_STATUS_FAILED,
        FLOW_RUN_STATUS_SKIPPED,
    }:
        update_fields["completed_at"] = _utc_now()

    collection = get_collection(EMAIL_FLOW_RUNS_COLLECTION)
    await collection.update_one(
        {"run_id": run_id.strip()},
        {"$set": update_fields},
    )


async def list_flow_runs_for_thread(
    *,
    thread_id: str,
    team_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    collection = get_collection(EMAIL_FLOW_RUNS_COLLECTION)
    cursor = (
        collection.find({
            "thread_id": thread_id.strip(),
            "team_id": team_id.strip(),
        })
        .sort("created_at", -1)
        .limit(max(limit, 1))
    )

    runs: List[Dict[str, Any]] = []
    async for run_doc in cursor:
        runs.append(serialize_flow_run(run_doc))
    return runs
