from fastapi import Request, HTTPException, status, Depends
import jwt  # PyJWT
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from config.settings import settings

def generate_jwt_token(payload: Dict[str, Any], expires_in_hours: Optional[int] = 24) -> str:
    """
    Generate a JWT token from a dictionary payload.
    
    Args:
        payload: Dictionary containing the data to encode in the token
        expires_in_hours: Number of hours until token expires (default: 24 hours)
        
    Returns:
        str: Encoded JWT token
        
    Example:
        token = generate_jwt_token({"user_id": "123", "email": "user@example.com"})
    """
    try:
        # Create a copy of the payload to avoid modifying the original
        token_payload = payload.copy()
        
        # Add expiration time (exp claim) if expires_in_hours is provided
        if expires_in_hours:
            exp = datetime.utcnow() + timedelta(hours=expires_in_hours)
            token_payload["exp"] = exp
        
        # Add issued at time (iat claim)
        token_payload["iat"] = datetime.utcnow()
        
        # Generate token using HS256 algorithm and JWT_SECRET
        token = jwt.encode(
            token_payload,
            settings.JWT_SECRET,
            algorithm="HS256"
        )
        
        return token
        
    except Exception as e:
        raise ValueError(f"Error generating JWT token: {str(e)}")

def decode_jwt_token(token: str) -> Dict[str, Any]:
    """
    Decode a JWT token and return the payload.
    
    Args:
        token: JWT token string to decode
        
    Returns:
        Dictionary containing:
            - success: bool - Whether the token is valid
            - message: str - Status message
            - Additional payload fields if successful
            
    Example:
        result = decode_jwt_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return {"success": True, "message": "Token is valid", **payload}
    except jwt.ExpiredSignatureError:
        return {"success": False, "message": "Token expired"}
    except jwt.InvalidTokenError as e:
        return {"success": False, "message": f"Invalid token: {str(e)}"}

def authorize_user(request: Request):
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        print("Missing or invalid Authorization header")
        return {"success": False, "message": "Missing or invalid Authorization header"}
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        print("Token is valid...")
        return {"success": True,"message": "Token is valid", **payload}

    except jwt.ExpiredSignatureError:
        print("Token expired...")
        return {"success": False, "message": "Token expired"}
    except jwt.InvalidTokenError:
        print("Invalid token...")
        return {"success": False, "message": "Invalid token"}
