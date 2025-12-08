from urllib.parse import parse_qs
import os
from logging_config import get_logger
from middlewares.jwt_middleware import decode_jwt_token

logger = get_logger()

def _strip_bearer(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    return v[len("Bearer "):].strip() if v.lower().startswith("bearer ") else v

def extract_user_data_from_token(jwt_token):
    try:
        decoded_token = decode_jwt_token(jwt_token )
        if decoded_token.get("success") == False:
            logger.error(decoded_token.get("message"))
            return None
        return decoded_token
    except Exception as e:
        logger.error(f"Error extracting token data from token: {e}")
        return None
    
def extract_token_from_socket_environ(environ, auth):
    """
    Collect token from auth, headers, env, or query-string.
    Decode user_data once. Store both in environ and return them.
    Never early-return; we exit exactly once.
    """
    token = None
    user_data = None

    try:
        # 1) socket.io auth payload
        if isinstance(auth, dict):
            raw = auth.get("token") or auth.get("Authorization")
            if raw:
                logger.info(f"[socket.io auth] received")
                token = _strip_bearer(str(raw))

        # 2) ASGI headers (common in FastAPI/Uvicorn)
        if not token:
            scope = environ.get("asgi.scope", {})
            headers = scope.get("headers", []) or environ.get("headers", [])
            for name_b, value_b in headers or []:
                name = name_b.decode().lower()
                if name in ("authorization", "token", "x-access-token"):
                    token = _strip_bearer(value_b.decode().strip())
                    # logger.info(f"[headers] token found in {name} : {token}")
                    break

        # 3) WSGI-style environ fallbacks
        if not token:
            for k in ("HTTP_AUTHORIZATION", "HTTP_TOKEN", "HTTP_X_ACCESS_TOKEN"):
                if environ.get(k):
                    token = _strip_bearer(str(environ[k]))
                    # logger.info(f"[environ] token found in {k}")
                    break

        # logger.info(f"Reveived Token: {token}")
        # Decode user once
        if token:
            try:
                user_data = extract_user_data_from_token(token)
                # logger.info(f"[jwt] user_data decoded")
            except Exception as e:
                logger.warning(f"[jwt] failed to decode token: {e}")

        return user_data

    except Exception as e:
        logger.error(f"Error extracting token from socket environ: {e}")
        # Ensure consistent shape on failure
        return None