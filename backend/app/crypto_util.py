from app.config import get_settings


def encrypt_secret(plain: str | None) -> str | None:
    if not plain:
        return None
    key = get_settings().fernet_key
    if not key:
        return plain
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key).encrypt(plain.encode()).decode()


def decrypt_secret(stored: str | None) -> str | None:
    if not stored:
        return None
    key = get_settings().fernet_key
    if not key:
        return stored
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key).decrypt(stored.encode()).decode()
