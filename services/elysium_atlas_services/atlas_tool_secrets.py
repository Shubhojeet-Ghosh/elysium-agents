import hashlib
from base64 import urlsafe_b64encode, urlsafe_b64decode

from config.settings import settings


def _derive_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_tool_token(token: str) -> str:
    """Obfuscate a tool auth token for storage using the server JWT secret."""
    key = _derive_key(settings.JWT_SECRET)
    data = token.encode("utf-8")
    encrypted = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
    return urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_tool_token(encrypted_token: str) -> str:
    """Restore a tool auth token previously stored with encrypt_tool_token."""
    key = _derive_key(settings.JWT_SECRET)
    encrypted = urlsafe_b64decode(encrypted_token.encode("ascii"))
    data = bytes(encrypted[i] ^ key[i % len(key)] for i in range(len(encrypted)))
    return data.decode("utf-8")
