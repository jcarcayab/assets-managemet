"""Symmetric encryption for secrets stored in the database (TOTP seeds, Plaid access tokens).

The key comes from FIELD_ENCRYPTION_KEY, falling back to SECRET_KEY. Changing it makes stored secrets
unreadable, so set FIELD_ENCRYPTION_KEY explicitly in production and keep it with your backups.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    material = settings.FIELD_ENCRYPTION_KEY or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(f"field-encryption:{material}".encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt secret: FIELD_ENCRYPTION_KEY/SECRET_KEY changed?") from exc
