"""
Demo customer-inquiry tool APIs — Mongo collection names and seed fixtures.

Used by the demo agent tool chain: lookup → create_lead | get_summary.
"""

DEMO_CUSTOMERS_COLLECTION = "demo_customers"
DEMO_TICKETS_COLLECTION = "demo_tickets"
DEMO_LEADS_COLLECTION = "demo_leads"

DEMO_CUSTOMER_SARAH_ID = "cust_sarah_acme"
DEMO_CUSTOMER_SARAH_EMAIL = "sarah@acme.com"

SEED_DEMO_CUSTOMERS: list[dict] = [
    {
        "customer_id": DEMO_CUSTOMER_SARAH_ID,
        "name": "Sarah Chen",
        "email": DEMO_CUSTOMER_SARAH_EMAIL,
        "company": "Acme Corp",
        "plan": "enterprise",
        "member_since": "2023-06-01",
        "account_manager": "Alex Rivera",
    },
]

SEED_DEMO_TICKETS: list[dict] = [
    {
        "ticket_id": "TKT-1042",
        "customer_id": DEMO_CUSTOMER_SARAH_ID,
        "subject": "Billing discrepancy on March invoice",
        "status": "open",
        "priority": "high",
    },
    {
        "ticket_id": "TKT-1038",
        "customer_id": DEMO_CUSTOMER_SARAH_ID,
        "subject": "SSO configuration for Acme Corp",
        "status": "open",
        "priority": "medium",
    },
]

DEMO_SCENARIO_SCRIPTS: list[dict] = [
    {
        "path": "returning_customer",
        "title": "Returning customer — account summary",
        "visitor_message": "Hi, I'm Sarah — sarah@acme.com. Can you tell me what's going on with my account?",
        "expected_tools": ["lookup_demo_customer", "get_demo_customer_summary"],
        "seed_email": DEMO_CUSTOMER_SARAH_EMAIL,
    },
    {
        "path": "new_lead",
        "title": "New visitor — create lead",
        "visitor_message": "We're a 35-person team looking at enterprise pricing.",
        "follow_up_message": "john@newco.com",
        "expected_tools": ["lookup_demo_customer", "create_demo_lead"],
        "demo_email": "john@newco.com",
    },
]
