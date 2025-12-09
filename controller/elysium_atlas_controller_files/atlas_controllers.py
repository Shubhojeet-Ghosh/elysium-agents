from typing import Dict, Any
from fastapi.responses import JSONResponse
from logging_config import get_logger
from services.elysium_atlas_services.agent_services import initialize_agent_build, create_agent_document

logger = get_logger()

async def pre_build_agent_operations_controller(requestData: Dict[str, Any],user: dict):
    try:
        agent_id = await create_agent_document()
        if agent_id is None:
            return JSONResponse(status_code=500, content={"success": False, "message": "Failed to create agent document"})
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Agent document created", "agent_id": agent_id})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while building the agent.", "error": str(e)})

async def build_agent_controller_v1(requestData,userData,background_tasks):
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        logger.info(f"User data: {userData}")
        
        logger.info(f"Building agent v1 with request data: {requestData}")
        
        # Store links in MongoDB
        background_tasks.add_task(initialize_agent_build,requestData)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Your agent is being build.", "agent_id": requestData.get("agent_id")})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while building the agent.", "error": str(e)})