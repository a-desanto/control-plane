import os
import secrets

import bcrypt

_KEY_PREFIX_LEN = 8
_KEY_BYTES = 32


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext_key, prefix, bcrypt_hash).

    plaintext_key is shown exactly once; store only the hash.
    """
    raw = secrets.token_hex(_KEY_BYTES)
    key = f"agk_{raw}"
    prefix = key[:_KEY_PREFIX_LEN]
    hashed = bcrypt.hashpw(key.encode(), bcrypt.gensalt()).decode()
    return key, prefix, hashed


def verify_api_key(plaintext: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode(), stored_hash.encode())
    except Exception:
        return False
