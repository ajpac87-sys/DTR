"""
Passwords. Copied unchanged in substance from InMotion security.py (scrypt,
salted, constant-time compare), which was already tested there.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Conservative defaults. n must be a power of two.
# n=2**14 with r=8, p=1 needs ~16 MB per hash — fine for login frequency,
# expensive for an attacker with a stolen database.
_N = 2 ** 14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_LEN = 32

_PREFIX = "scrypt"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    # scrypt's maxmem default will reject very large n*r*p; guard input size
    # so an enormous password cannot be used to burn CPU.
    if len(password.encode("utf-8")) > 1024:
        raise ValueError("password too long")

    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_N, r=_R, p=_P,
        dklen=_KEY_LEN,
        maxmem=64 * 1024 * 1024,
    )
    return f"{_PREFIX}${_N}${_R}${_P}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """
    Check a plaintext password against a stored hash.

    Returns False on any malformed input rather than raising, so that a
    corrupted record cannot be distinguished from a wrong password by timing
    or by exception type.
    """
    if not isinstance(password, str) or not isinstance(stored, str):
        return False

    try:
        prefix, n_s, r_s, p_s, salt_s, hash_s = stored.split("$")
        if prefix != _PREFIX:
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = _b64d(salt_s)
        expected = _b64d(hash_s)
    except (ValueError, AttributeError):
        return False

    # Refuse absurd parameters from a tampered record rather than allocating
    # gigabytes of memory trying to honour them.
    if n > 2 ** 20 or r > 32 or p > 16 or len(expected) > 128:
        return False

    try:
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n, r=r, p=p,
            dklen=len(expected),
            maxmem=256 * 1024 * 1024,
        )
    except (ValueError, MemoryError):
        return False

    return hmac.compare_digest(actual, expected)


MIN_PASSWORD_LENGTH = 8


def password_ok(pw: str) -> bool:
    return isinstance(pw, str) and MIN_PASSWORD_LENGTH <= len(pw) <= 256
