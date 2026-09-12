from base64 import urlsafe_b64decode, urlsafe_b64encode
import hashlib

from config.settings import settings


def _derive_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_plugin_secret(value: str) -> str:
    """Encrypt a plugin secret for Mongo using APPLICATION_PASSKEY."""
    key = _derive_key(settings.APPLICATION_PASSKEY)
    data = value.encode("utf-8")
    encrypted = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
    return urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_plugin_secret(encrypted_value: str) -> str:
    """Restore a plugin secret previously stored with encrypt_plugin_secret."""
    key = _derive_key(settings.APPLICATION_PASSKEY)
    encrypted = urlsafe_b64decode(encrypted_value.encode("ascii"))
    data = bytes(encrypted[i] ^ key[i % len(key)] for i in range(len(data)))
    return data.decode("utf-8")
