from fastapi.responses import JSONResponse

from config.demo_customer_inquiry_config import DEMO_SCENARIO_SCRIPTS
from config.demo_customer_inquiry_models import (
    CreateDemoLeadRequest,
    LookupDemoCustomerRequest,
)
from logging_config import get_logger
from services.demo.demo_customer_inquiry_services import (
    create_demo_lead,
    get_demo_customer_summary,
    lookup_demo_customer,
    reset_demo_customer_inquiry_data,
    seed_demo_customer_inquiry_data,
)

logger = get_logger()


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"success": False, "message": "You are unauthorized to access this resource."},
    )


async def lookup_demo_customer_controller(body: LookupDemoCustomerRequest) -> JSONResponse:
    try:
        result = await lookup_demo_customer(body.email)
        return JSONResponse(status_code=200, content={"success": True, **result})
    except Exception as exc:
        logger.error(f"Error in lookup_demo_customer_controller: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while looking up the customer."},
        )


async def get_demo_customer_summary_controller(customer_id: str) -> JSONResponse:
    try:
        normalized_id = customer_id.strip()
        if not normalized_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "customer_id cannot be empty."},
            )

        result = await get_demo_customer_summary(normalized_id)
        if not result.get("success"):
            return JSONResponse(
                status_code=result.get("status_code", 404),
                content={"success": False, "message": result.get("message", "Customer not found.")},
            )

        return JSONResponse(status_code=200, content=result)
    except Exception as exc:
        logger.error(f"Error in get_demo_customer_summary_controller: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching the customer summary."},
        )


async def create_demo_lead_controller(body: CreateDemoLeadRequest) -> JSONResponse:
    try:
        result = await create_demo_lead(
            body.email,
            name=body.name,
            company=body.company,
            interest=body.interest,
        )
        if not result.get("success"):
            return JSONResponse(
                status_code=result.get("status_code", 400),
                content={
                    "success": False,
                    "message": result.get("message", "Unable to create lead."),
                    "customer_id": result.get("customer_id"),
                },
            )

        return JSONResponse(status_code=200, content=result)
    except Exception as exc:
        logger.error(f"Error in create_demo_lead_controller: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while creating the lead."},
        )


async def seed_demo_customer_inquiry_controller(authorized: bool) -> JSONResponse:
    try:
        if not authorized:
            return _unauthorized_response()

        result = await seed_demo_customer_inquiry_data()
        return JSONResponse(status_code=200, content=result)
    except Exception as exc:
        logger.error(f"Error in seed_demo_customer_inquiry_controller: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while seeding demo data."},
        )


async def reset_demo_customer_inquiry_controller(authorized: bool) -> JSONResponse:
    try:
        if not authorized:
            return _unauthorized_response()

        result = await reset_demo_customer_inquiry_data()
        return JSONResponse(status_code=200, content=result)
    except Exception as exc:
        logger.error(f"Error in reset_demo_customer_inquiry_controller: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while resetting demo data."},
        )


async def get_demo_scenario_controller() -> JSONResponse:
    try:
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "scenarios": DEMO_SCENARIO_SCRIPTS,
                "tool_names": [
                    "lookup_demo_customer",
                    "create_demo_lead",
                    "get_demo_customer_summary",
                ],
            },
        )
    except Exception as exc:
        logger.error(f"Error in get_demo_scenario_controller: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching demo scenarios."},
        )
