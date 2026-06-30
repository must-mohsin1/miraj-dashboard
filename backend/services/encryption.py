"""Fernet symmetric encryption for MEXC API key storage.

Provides ``encrypt_api_key`` and ``decrypt_api_key`` backed by
``cryptography.fernet.Fernet``.  The encryption key is read from the
``FERNET_ENCRYPTION_KEY`` environment variable (base64-encoded 32-byte key)
on the first call — the module is importable without side effects (lazy init).

Usage::

    from backend.services.encryption import encrypt_api_key, decrypt_api_key

    cipher = encrypt_api_key("my-mexc-api-key")
    plain  = decrypt_api_key(cipher)  # -> "my-mexc-api-key"

Raises ``ValueError`` if ``FERNET_ENCRYPTION_KEY`` is not set or is empty.
Raises ``cryptography.fernet.InvalidToken`` when decrypting invalid data.

.. important::

   Never log or print key material.  This module must not expose plaintext
   keys in logs, tracebacks, or error messages.

"""

from __future__ import annotations

import os

__all__ = ["encrypt_api_key", "decrypt_api_key"]

# Module-level cache — avoids re-reading the env var on every call.
# Initialised to None; set once by _get_fernet() on first use.
_fernet = None


def encrypt_api_key(plaintext: str) -> bytes:
    """Encrypt *plaintext* and return the Fernet ciphertext.

    Parameters
    ----------
    plaintext:
        The API key or secret to encrypt.

    Returns
    -------
    bytes
        URL-safe base64-encoded Fernet token (includes IV + HMAC).

    Raises
    ------
    ValueError
        If ``FERNET_ENCRYPTION_KEY`` is not set or empty.
    """
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8"))


def decrypt_api_key(ciphertext: bytes) -> str:
    """Decrypt *ciphertext* and return the original plaintext.

    Parameters
    ----------
    ciphertext:
        Fernet token previously produced by :func:`encrypt_api_key`.

    Returns
    -------
    str
        The original plaintext.

    Raises
    ------
    ValueError
        If ``FERNET_ENCRYPTION_KEY`` is not set or empty.
    cryptography.fernet.InvalidToken
        If *ciphertext* is malformed, tampered with, or was encrypted with
        a different key.
    """
    f = _get_fernet()
    return f.decrypt(ciphertext).decode("utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_fernet():
    """Return a :class:`cryptography.fernet.Fernet` instance (lazy-init).

    The instance is cached after the first call so the env var is read only
    once per process lifetime.
    """
    global _fernet
    if _fernet is not None:
        return _fernet

    from cryptography.fernet import Fernet

    key = os.environ.get("FERNET_ENCRYPTION_KEY")
    if not key:
        raise ValueError(
            "FERNET_ENCRYPTION_KEY is not set or is empty — cannot initialise "
            "encryption.  Set a base64-encoded 32-byte key in your .env file."
        )

    _fernet = Fernet(key)
    return _fernet
