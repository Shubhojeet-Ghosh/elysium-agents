import uuid
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from config.atlas_support_ticket_models import (
    CreateSupportTicketRequest,
    InternalUpdateSupportTicketRequest,
    TicketStatus,
)
from logging_config import get_logger
from services.mongo_services import get_collection

logger = get_logger()

TICKETS_COLLECTION = "atlas_support_tickets"


def _serialize_comment(comment: dict[str, Any]) -> dict[str, Any]:
    created_at = comment.get("created_at")
    return {
        "comment_id": comment.get("comment_id"),
        "body": comment.get("body"),
        "author_type": comment.get("author_type"),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
    }


def _serialize_ticket_summary(document: dict[str, Any]) -> dict[str, Any]:
    created_at = document.get("created_at")
    updated_at = document.get("updated_at")
    last_activity_at = document.get("last_activity_at")

    return {
        "ticket_id": str(document["_id"]),
        "ticket_number": document.get("ticket_number"),
        "team_id": document.get("team_id"),
        "created_by_user_id": document.get("created_by_user_id"),
        "subject": document.get("subject"),
        "status": document.get("status"),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
        "last_activity_at": (
            last_activity_at.isoformat() if isinstance(last_activity_at, datetime) else last_activity_at
        ),
    }


def _serialize_ticket_detail(document: dict[str, Any]) -> dict[str, Any]:
    summary = _serialize_ticket_summary(document)
    comments = document.get("comments") or []
    summary["description"] = document.get("description")
    summary["comments"] = [_serialize_comment(comment) for comment in comments]
    return summary


def _build_ticket_number(ticket_object_id: ObjectId) -> str:
    year = datetime.now(timezone.utc).year
    return f"TKT-{year}-{ticket_object_id}"


async def create_support_ticket(
    team_id: str,
    user_id: str,
    request: CreateSupportTicketRequest,
) -> dict[str, Any]:
    current_time = datetime.now(timezone.utc)
    ticket_object_id = ObjectId()
    ticket_number = _build_ticket_number(ticket_object_id)

    document = {
        "_id": ticket_object_id,
        "ticket_number": ticket_number,
        "team_id": team_id,
        "created_by_user_id": user_id,
        "subject": request.subject.strip(),
        "description": request.description.strip(),
        "status": "open",
        "comments": [],
        "created_at": current_time,
        "updated_at": current_time,
        "last_activity_at": current_time,
    }

    collection = get_collection(TICKETS_COLLECTION)
    result = await collection.insert_one(document)
    document["_id"] = result.inserted_id

    logger.info(
        f"Created support ticket ticket_id={result.inserted_id} "
        f"ticket_number={ticket_number} user_id={user_id} team_id={team_id}"
    )
    return {"success": True, "ticket": _serialize_ticket_detail(document)}


async def list_my_support_tickets(
    team_id: str,
    user_id: str,
    *,
    page: int = 1,
    limit: int = 20,
    status: TicketStatus | None = None,
) -> dict[str, Any]:
    collection = get_collection(TICKETS_COLLECTION)
    query: dict[str, Any] = {
        "team_id": team_id,
        "created_by_user_id": user_id,
    }
    if status is not None:
        query["status"] = status

    total = await collection.count_documents(query)
    skip = (page - 1) * limit
    cursor = (
        collection.find(query)
        .sort([("last_activity_at", -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
    )
    documents = await cursor.to_list(length=limit)
    tickets = [_serialize_ticket_summary(doc) for doc in documents]
    total_pages = max(1, (total + limit - 1) // limit) if total else 0

    return {
        "success": True,
        "tickets": tickets,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1 and total > 0,
    }


async def get_support_ticket_by_number(ticket_number: str) -> dict[str, Any] | None:
    try:
        collection = get_collection(TICKETS_COLLECTION)
        document = await collection.find_one({"ticket_number": ticket_number.strip()})
        if not document:
            return None
        return _serialize_ticket_detail(document)
    except Exception as e:
        logger.error(f"Error fetching ticket_number={ticket_number}: {e}", exc_info=True)
        return None


async def internal_update_support_ticket(
    request: InternalUpdateSupportTicketRequest,
) -> dict[str, Any]:
    try:
        collection = get_collection(TICKETS_COLLECTION)
        query: dict[str, Any]
        if request.ticket_id:
            query = {"_id": ObjectId(request.ticket_id)}
        else:
            query = {"ticket_number": request.ticket_number.strip()}

        existing = await collection.find_one(query)
        if not existing:
            return {"success": False, "message": "Ticket not found.", "status_code": 404}

        current_time = datetime.now(timezone.utc)
        updates: dict[str, Any] = {
            "updated_at": current_time,
            "last_activity_at": current_time,
        }
        push_comment: dict[str, Any] | None = None

        if request.status is not None:
            updates["status"] = request.status

        if request.comment is not None:
            push_comment = {
                "comment_id": str(uuid.uuid4()),
                "body": request.comment.strip(),
                "author_type": "support",
                "created_at": current_time,
            }

        update_doc: dict[str, Any] = {"$set": updates}
        if push_comment is not None:
            update_doc["$push"] = {"comments": push_comment}

        await collection.update_one({"_id": existing["_id"]}, update_doc)
        updated = await collection.find_one({"_id": existing["_id"]})

        logger.info(
            f"Internally updated support ticket ticket_id={existing['_id']} "
            f"status={request.status} comment_added={push_comment is not None}"
        )
        return {"success": True, "ticket": _serialize_ticket_detail(updated)}

    except InvalidId:
        return {"success": False, "message": "Ticket not found.", "status_code": 404}
    except Exception as e:
        logger.error(f"Error internally updating support ticket: {e}", exc_info=True)
        return {"success": False, "message": "An error occurred while updating the ticket."}
