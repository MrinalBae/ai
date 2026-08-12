import base64
import hashlib
from cryptography.fernet import Fernet

def _fernet(secret: str) -> Fernet:
    if not secret:
        raise RuntimeError("SETTINGS_ENCRYPTION_KEY is not configured.")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)

def encrypt_secret(value: str, secret: str) -> str:
    return _fernet(secret).encrypt(value.encode()).decode()

def decrypt_secret(value: str, secret: str) -> str:
    return _fernet(secret).decrypt(value.encode()).decode()

def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "••••••••"
    return value[:4] + "••••••••" + value[-4:]
