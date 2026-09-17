"""
Encryption utilities for storing credentials securely.

Preferences for key source:
1. JOBPILOT_SECRET_KEY environment variable
2. local .secret.key fallback file
3. generated in-place if nothing else is configured
"""

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet

KEY_FILE = Path(__file__).parent.parent / ".secret.key"


def _normalize_secret(secret: str) -> bytes:
    """Convert a human-friendly secret into a valid Fernet key."""
    secret = (secret or "").strip()
    if not secret:
        raise ValueError("Secret cannot be empty")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_or_create_key() -> bytes:
    """Load or generate the encryption key for this machine."""
    env_key = os.getenv("JOBPILOT_SECRET_KEY")
    if env_key:
        return _normalize_secret(env_key)

    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()

    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    try:
        KEY_FILE.chmod(0o600)
    except Exception:
        pass
    return key


def get_fernet() -> Fernet:
    return Fernet(_get_or_create_key())


def encrypt(text: str) -> str:
    if not text:
        return ""
    return get_fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except Exception:
        return ""
