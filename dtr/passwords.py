"""
Passwords.

A password is never stored. What's stored is a one-way fingerprint made with
scrypt (built into Python), salted so two people with the same password get
different fingerprints. Checking a password redoes the fingerprint and
compares the two in constant time.

Stored form:  dtr1:<cost>:<salt>:<fingerprint>   (salt and fingerprint in hex)
"""
from __future__ import annotations

import hashlib
import hmac
import os

VERSION = "dtr1"
COST = 15                    # scrypt N = 2**COST; about 32 MB of memory per check
BLOCK, PARALLEL, LENGTH = 8, 1, 32
MIN_LENGTH, MAX_LENGTH = 8, 256


def _fingerprint(password: str, salt: bytes, cost: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** cost,
                          r=BLOCK, p=PARALLEL, dklen=LENGTH,
                          maxmem=128 * 1024 * 1024)


def password_ok(pw: str) -> bool:
    """Long enough to be worth having, short enough not to be a weapon."""
    return isinstance(pw, str) and MIN_LENGTH <= len(pw) <= MAX_LENGTH


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password or len(password) > MAX_LENGTH:
        raise ValueError("password must be 1 to 256 characters")
    salt = os.urandom(16)
    return f"{VERSION}:{COST}:{salt.hex()}:{_fingerprint(password, salt, COST).hex()}"


def verify_password(password: str, stored: str) -> bool:
    """
    True only for the right password. Anything odd about the stored value
    (wrong version, damaged, a cost nobody would set) is simply False.
    """
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    if len(password) > MAX_LENGTH:
        return False
    try:
        version, cost, salt, want = stored.split(":")
        cost = int(cost)
        salt, want = bytes.fromhex(salt), bytes.fromhex(want)
    except ValueError:
        return False
    if version != VERSION or not 10 <= cost <= 18 or len(want) != LENGTH:
        return False
    return hmac.compare_digest(_fingerprint(password, salt, cost), want)
