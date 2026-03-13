import json
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


class CredentialService:
    """Encrypt and decrypt OAuth credentials using Fernet symmetric encryption."""

    def __init__(self) -> None:
        key = settings.encryption_key
        if not key:
            raise RuntimeError("ENCRYPTION_KEY env var is not set")
        self._fernet = Fernet(key.encode())

    def encrypt(self, data: dict) -> bytes:
        payload = json.dumps(data).encode()
        return self._fernet.encrypt(payload)

    def decrypt(self, encrypted: bytes) -> dict | None:
        try:
            payload = self._fernet.decrypt(encrypted)
            return json.loads(payload)
        except (InvalidToken, json.JSONDecodeError) as e:
            logger.warning("Credential decryption failed: %s", e)
            return None

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.encryption_key)
