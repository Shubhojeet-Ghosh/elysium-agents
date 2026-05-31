from typing import Any, Dict

from fastapi.responses import JSONResponse

from logging_config import get_logger
from services.elysium_atlas_services.atlas_stale_visitor_services import cleanup_stale_visitors_service

logger = get_logger()


async def cleanup_stale_visitors_controller(
    authorized: bool,
    threshold_seconds: int | None = None,
    emit_events: bool = True,
) -> JSONResponse:
    try:
        if not authorized:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "You are unauthorized to access this resource."},
            )

        logger.info("cleanup_stale_visitors_controller invoked")
        result: Dict[str, Any] = await cleanup_stale_visitors_service(
            threshold_seconds=threshold_seconds,
            emit_events=emit_events,
        )

        status_code = 200 if result.get("success") else 500
        return JSONResponse(status_code=status_code, content=result)

    except Exception as e:
        logger.error(f"Error in cleanup_stale_visitors_controller: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Failed to cleanup stale visitors.", "error": str(e)},
        )
