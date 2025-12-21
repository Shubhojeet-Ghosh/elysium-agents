from typing import Dict, Any
from fastapi.responses import JSONResponse
from logging_config import get_logger
from services.elysium_atlas_services.agent_services import initialize_agent_build_update, create_agent_document
from config.atlas_agent_config_data import ELYSIUM_ATLAS_AGENT_CONFIG_DATA
from config.elysium_atlas_s3_config import ELYSIUM_ATLAS_BUCKET_NAME, ELYSIUM_CDN_BASE_URL, ELYSIUM_GLOBAL_BUCKET_NAME
from services.aws_services.s3_service import generate_presigned_upload_url

logger = get_logger()

async def pre_build_agent_operations_controller(requestData: Dict[str, Any],userData: dict):
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        # logger.info(f"User data: {userData}")

        user_id = userData.get("user_id")

        initial_data = ELYSIUM_ATLAS_AGENT_CONFIG_DATA.get("agent_init_config")
        
        initial_data["owner_user_id"] = user_id

        if requestData.get("agent_name") is not None:
            initial_data["agent_name"] = requestData.get("agent_name")

        agent_id = await create_agent_document(initial_data)
        if agent_id is None:
            return JSONResponse(status_code=500, content={"success": False, "message": "Failed to create the agent."})
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Agent created successfully.", "agent_id": agent_id})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while building the agent.", "error": str(e)})

async def build_update_agent_controller_v1(requestData,userData,background_tasks):
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        logger.info(f"User data: {userData}")
        
        logger.info(f"buil/update agent with request data: {requestData}")
        
        # Store links in MongoDB
        background_tasks.add_task(initialize_agent_build_update,requestData)
        
        return JSONResponse(status_code=200, content={"success": True, "message": "Your agent is being build.", "agent_id": requestData.get("agent_id")})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while building the agent.", "error": str(e)})

async def generate_presigned_url_controller(requestData,userData):
    try:
        if userData is None or userData.get("success") == False:
            return JSONResponse(status_code=401, content={"success": False, "message": userData.get("message")})
        
        logger.info(f"User data: {userData}")
        
        presigned_urls = dict[Any, Any]()

        files = requestData.get("files")
        presigned_urls_for_files = []
        if files:
            for file in files:
                folder_path = file.get("folder_path")
                filename = file.get("filename")
                filetype = file.get("filetype")
                visibility = file.get("visibility","private")
                
                # Use ELYSIUM_GLOBAL_BUCKET_NAME if visibility is "public", otherwise use ELYSIUM_ATLAS_BUCKET_NAME
                bucket_name = ELYSIUM_GLOBAL_BUCKET_NAME if visibility == "public" else ELYSIUM_ATLAS_BUCKET_NAME
                
                # Add "elysium-atlas/" prefix to folder_path if visibility is "public"
                if visibility == "public":
                    folder_path = f"elysium-atlas/{folder_path}" if folder_path else "elysium-atlas"
                
                presigned_url = generate_presigned_upload_url(bucket_name, folder_path, filename, filetype, visibility=visibility)
                if presigned_url:
                    presigned_urls_for_files.append(presigned_url)
        
        presigned_urls["files"] = presigned_urls_for_files

        return JSONResponse(status_code=200, content={"success": True, "message": "Presigned urls generated", "presigned_urls": presigned_urls})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"An error occurred while generating presigned urls.", "error": str(e)})