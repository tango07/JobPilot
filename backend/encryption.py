"""
Encryption utilities for storing credentials securely.
Uses Fernet symmetric encryption with a machine-specific key.
"""

import os
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

KEY_FILE = Path(__file__).parent.parent / ".secret.key"


def _get_or_create_key() -> bytes:
    """Load or generate the encryption key for this machine."""
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    KEY_FILE.chmod(0o600)
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
