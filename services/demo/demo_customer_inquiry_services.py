import uuid
from datetime import datetime, timezone
from typing import Any

from config.demo_customer_inquiry_config import (
    DEMO_CUSTOMERS_COLLECTION,
    DEMO_CUSTOMER_SARAH_EMAIL,
    DEMO_LEADS_COLLECTION,
    DEMO_TICKETS_COLLECTION,
    SEED_DEMO_CUSTOMERS,
    SEED_DEMO_TICKETS,
)
from logging_config import get_logger
from services.mongo_services import get_collection

logger = get_logger()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_demo_email(email: str) -> str:
    return email.strip().lower()


async def lookup_demo_customer(email: str) -> dict[str, Any]:
    """Return whether a demo customer exists for the given email."""
    normalized_email = normalize_demo_email(email)
    collection = get_collection(DEMO_CUSTOMERS_COLLECTION)
    document = await collection.find_one({"email": normalized_email})

    if not document:
        return {
            "found": False,
            "email": normalized_email,
        }

    return {
        "found": True,
        "customer_id": document.get("customer_id"),
        "name": document.get("name"),
        "company": document.get("company"),
        "email": document.get("email"),
        "plan": document.get("plan"),
    }


def _build_suggestions(customer: dict[str, Any], open_tickets: list[dict[str, Any]]) -> list[str]:
    suggestions: list[str] = []
    account_manager = customer.get("account_manager") or "your account manager"

    if open_tickets:
        sorted_tickets = sorted(
            open_tickets,
            key=lambda ticket: {"high": 0, "medium": 1, "low": 2}.get(ticket.get("priority", "low"), 3),
        )
        top_ticket = sorted_tickets[0]
        suggestions.append(
            f"Your highest-priority open item is {top_ticket.get('ticket_id')} "
            f"({top_ticket.get('subject')}) — reply on that ticket or contact {account_manager}."
        )

        billing_tickets = [
            ticket
            for ticket in open_tickets
            if "billing" in str(ticket.get("subject", "")).lower()
        ]
        if billing_tickets:
            billing_ticket = billing_tickets[0]
            suggestions.append(
                f"If your question is about billing, focus on {billing_ticket.get('ticket_id')} "
                f"({billing_ticket.get('subject')})."
            )

        sso_tickets = [
            ticket
            for ticket in open_tickets
            if "sso" in str(ticket.get("subject", "")).lower()
        ]
        if sso_tickets:
            sso_ticket = sso_tickets[0]
            suggestions.append(
                f"For SSO setup, track progress on {sso_ticket.get('ticket_id')} "
                f"({sso_ticket.get('subject')})."
            )

    plan = str(customer.get("plan") or "").lower()
    if plan == "enterprise":
        suggestions.append(
            "Enterprise plans include priority support; mention your ticket ID if you need expedited review."
        )

    return suggestions[:4]


async def get_demo_customer_summary(customer_id: str) -> dict[str, Any]:
    """Return plan, open tickets, and suggested next steps for a demo customer."""
    collection = get_collection(DEMO_CUSTOMERS_COLLECTION)
    customer = await collection.find_one({"customer_id": customer_id.strip()})
    if not customer:
        return {"success": False, "message": "Customer not found.", "status_code": 404}

    tickets_collection = get_collection(DEMO_TICKETS_COLLECTION)
    cursor = tickets_collection.find(
        {"customer_id": customer_id.strip(), "status": "open"},
    )
    open_tickets = await cursor.to_list(length=50)

    ticket_payload = [
        {
            "ticket_id": ticket.get("ticket_id"),
            "subject": ticket.get("subject"),
            "status": ticket.get("status"),
            "priority": ticket.get("priority"),
        }
        for ticket in open_tickets
    ]

    summary = {
        "success": True,
        "customer_id": customer.get("customer_id"),
        "name": customer.get("name"),
        "company": customer.get("company"),
        "email": customer.get("email"),
        "plan": customer.get("plan"),
        "member_since": customer.get("member_since"),
        "account_manager": customer.get("account_manager"),
        "open_tickets_count": len(ticket_payload),
        "open_tickets": ticket_payload,
        "suggestions": _build_suggestions(customer, open_tickets),
    }
    return summary


async def create_demo_lead(
    email: str,
    *,
    name: str | None = None,
    company: str | None = None,
    interest: str | None = None,
) -> dict[str, Any]:
    """Create a demo sales lead when lookup returns found=false."""
    normalized_email = normalize_demo_email(email)
    customers_collection = get_collection(DEMO_CUSTOMERS_COLLECTION)
    existing_customer = await customers_collection.find_one({"email": normalized_email})
    if existing_customer:
        return {
            "success": False,
            "message": "Customer already exists. Use get_demo_customer_summary instead.",
            "status_code": 409,
            "customer_id": existing_customer.get("customer_id"),
        }

    leads_collection = get_collection(DEMO_LEADS_COLLECTION)
    existing_lead = await leads_collection.find_one({"email": normalized_email, "status": "new"})
    if existing_lead:
        return {
            "success": True,
            "lead_id": existing_lead.get("lead_id"),
            "status": existing_lead.get("status"),
            "email": normalized_email,
            "message": "Lead already captured for sales follow-up.",
            "duplicate": True,
        }

    lead_id = f"lead_{uuid.uuid4().hex[:12]}"
    created_at = _utc_now()
    document = {
        "lead_id": lead_id,
        "email": normalized_email,
        "name": name,
        "company": company,
        "interest": interest,
        "status": "new",
        "source": "demo_agent_tool",
        "created_at": created_at,
        "updated_at": created_at,
    }
    await leads_collection.insert_one(document)
    logger.info(f"Created demo lead lead_id={lead_id} email={normalized_email}")

    return {
        "success": True,
        "lead_id": lead_id,
        "status": "new",
        "email": normalized_email,
        "name": name,
        "company": company,
        "interest": interest,
        "message": "Lead captured for sales follow-up.",
        "duplicate": False,
    }


async def seed_demo_customer_inquiry_data() -> dict[str, Any]:
    """Idempotently seed Sarah (returning customer) and her open tickets; clear demo leads."""
    customers_collection = get_collection(DEMO_CUSTOMERS_COLLECTION)
    tickets_collection = get_collection(DEMO_TICKETS_COLLECTION)
    leads_collection = get_collection(DEMO_LEADS_COLLECTION)

    seeded_customers = 0
    for customer in SEED_DEMO_CUSTOMERS:
        result = await customers_collection.update_one(
            {"customer_id": customer["customer_id"]},
            {"$set": customer},
            upsert=True,
        )
        if result.upserted_id is not None or result.modified_count > 0:
            seeded_customers += 1

    seeded_tickets = 0
    for ticket in SEED_DEMO_TICKETS:
        result = await tickets_collection.update_one(
            {"ticket_id": ticket["ticket_id"]},
            {"$set": ticket},
            upsert=True,
        )
        if result.upserted_id is not None or result.modified_count > 0:
            seeded_tickets += 1

    leads_deleted = (await leads_collection.delete_many({})).deleted_count

    return {
        "success": True,
        "seeded_customers": seeded_customers,
        "seeded_tickets": seeded_tickets,
        "cleared_leads": leads_deleted,
        "demo_returning_customer_email": DEMO_CUSTOMER_SARAH_EMAIL,
    }


async def reset_demo_customer_inquiry_data() -> dict[str, Any]:
    """Remove all demo customer-inquiry documents."""
    customers_deleted = (
        await get_collection(DEMO_CUSTOMERS_COLLECTION).delete_many({})
    ).deleted_count
    tickets_deleted = (
        await get_collection(DEMO_TICKETS_COLLECTION).delete_many({})
    ).deleted_count
    leads_deleted = (
        await get_collection(DEMO_LEADS_COLLECTION).delete_many({})
    ).deleted_count

    logger.info(
        "Reset demo customer inquiry data "
        f"(customers={customers_deleted}, tickets={tickets_deleted}, leads={leads_deleted})"
    )
    return {
        "success": True,
        "deleted_customers": customers_deleted,
        "deleted_tickets": tickets_deleted,
        "deleted_leads": leads_deleted,
    }
