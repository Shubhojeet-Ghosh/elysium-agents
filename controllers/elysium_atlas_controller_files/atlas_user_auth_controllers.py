from typing import Dict, Any
from fastapi.responses import JSONResponse
from middlewares.jwt_middleware import generate_jwt_token, decode_jwt_token

from config.settings import settings

def generate_jwt_token_controller(requestData: Dict[str, Any]):
    try:
        application_passkey = requestData.get("application_passkey")
        if application_passkey is None or application_passkey != settings.APPLICATION_PASSKEY:
            return JSONResponse(status_code=401, content={"success": False, "message": "Invalid application passkey"})
        
        payload = requestData.get("payload")

        if payload is None or payload == "":
            return JSONResponse(status_code=400, content={"success": False, "message": "Payload is required"})
        
        jwt_token = generate_jwt_token(payload = payload, expires_in_hours=168)
        
        # Decode the token to verify and see the decoded payload
        decoded_token = decode_jwt_token(jwt_token)
        
        return JSONResponse(
            status_code=200, 
            content={
                "success": True, 
                "message": "JWT token generated successfully", 
                "token": jwt_token,
                "decoded_token": decoded_token
            }
        )

    except Exception as e:
        return ({
            "success": False,
            "message": f"An error occurred while generating the JWT token.",
            "error": str(e)
        })