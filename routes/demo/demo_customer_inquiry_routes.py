from fastapi import APIRouter, Depends, Query

from config.demo_customer_inquiry_models import CreateDemoLeadRequest, LookupDemoCustomerRequest
from controllers.demo_controller_files.demo_customer_inquiry_controllers import (
    create_demo_lead_controller,
    get_demo_customer_summary_controller,
    get_demo_scenario_controller,
    lookup_demo_customer_controller,
    reset_demo_customer_inquiry_controller,
    seed_demo_customer_inquiry_controller,
)
from middlewares.application_passkey_auth import verify_application_passkey

demo_customer_inquiry_router = APIRouter(
    prefix="/demo/customer-inquiry/v1",
    tags=["Demo - Customer Inquiry Tools"],
)


@demo_customer_inquiry_router.post("/customers/lookup")
async def lookup_demo_customer_route(body: LookupDemoCustomerRequest):
    """Tool: lookup_demo_customer — check if email exists in demo CRM (open, no auth)."""
    return await lookup_demo_customer_controller(body)


@demo_customer_inquiry_router.get("/customers/summary")
async def get_demo_customer_summary_route(
    customer_id: str = Query(..., min_length=1, max_length=128),
):
    """Tool: get_demo_customer_summary — plan, open tickets, and suggestions (open, no auth)."""
    return await get_demo_customer_summary_controller(customer_id)


@demo_customer_inquiry_router.post("/leads")
async def create_demo_lead_route(body: CreateDemoLeadRequest):
    """Tool: create_demo_lead — capture a new sales lead (open, no auth)."""
    return await create_demo_lead_controller(body)


@demo_customer_inquiry_router.post("/admin/seed")
async def seed_demo_customer_inquiry_route(
    authorized: bool = Depends(verify_application_passkey),
):
    """Seed Sarah (returning customer) + tickets; clears demo leads. Passkey required."""
    return await seed_demo_customer_inquiry_controller(authorized)


@demo_customer_inquiry_router.post("/admin/reset")
async def reset_demo_customer_inquiry_route(
    authorized: bool = Depends(verify_application_passkey),
):
    """Delete all demo customer-inquiry Mongo data. Passkey required."""
    return await reset_demo_customer_inquiry_controller(authorized)


@demo_customer_inquiry_router.get("/admin/scenario")
async def get_demo_scenario_route():
    """Return suggested demo visitor prompts and expected tool flows (open, no auth)."""
    return await get_demo_scenario_controller()
