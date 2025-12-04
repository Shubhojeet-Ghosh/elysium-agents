from typing import Dict, Any
from middlewares.jwt_middleware import generate_jwt_token
from controller.elysium_atlas_controller_files.atlas_user_auth_controllers import generate_jwt_token_controller
from fastapi import APIRouter

elysium_atlas_user_auth_router = APIRouter(prefix = "/elysium-atlas/user-auth",tags=["Elysium Atlas User Auth"])

#  method to generate a JWT token for the user using the passphrase and payload
@elysium_atlas_user_auth_router.post("/v1/generate-jwt-token")
def generate_jwt_token_route(requestData: Dict[str, Any]):
    return generate_jwt_token_controller(requestData)
