"""Tests for backend/services/encryption.py — Fernet encryption service.

Run with::

    cd <project-root>
    python -m pytest backend/services/test_encryption.py -v

"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Pre-generated Fernet key (base64-encoded 32-byte) for testing
_TEST_FERNET_KEY = "0ZPoaILsouPMg4bPfFmbZpxeCMpEicO_c8sEcwXIJPI="
_PLAINTEXT = "my-mexc-api-key-12345"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_module():
    """Import the encryption module fresh (no cached imports)."""
    import importlib
    from backend.services import encryption
    importlib.reload(encryption)
    return encryption


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    """encrypt_api_key / decrypt_api_key round-trip and edge cases."""

    def test_round_trip(self, monkeypatch):
        """Encrypt then decrypt returns the original plaintext."""
        monkeypatch.setenv("FERNET_ENCRYPTION_KEY", _TEST_FERNET_KEY)
        mod = _import_module()

        ciphertext = mod.encrypt_api_key(_PLAINTEXT)
        assert isinstance(ciphertext, bytes)

        decrypted = mod.decrypt_api_key(ciphertext)
        assert decrypted == _PLAINTEXT

    def test_round_trip_unicode(self, monkeypatch):
        """Round-trip works with non-ASCII / special characters."""
        monkeypatch.setenv("FERNET_ENCRYPTION_KEY", _TEST_FERNET_KEY)
        mod = _import_module()

        plaintext = "MEXC-🔑-api_key!@#$%^&*()"
        ciphertext = mod.encrypt_api_key(plaintext)
        assert mod.decrypt_api_key(ciphertext) == plaintext

    def test_value_error_when_key_missing(self, monkeypatch):
        """Raises ValueError when FERNET_ENCRYPTION_KEY is not set."""
        monkeypatch.delenv("FERNET_ENCRYPTION_KEY", raising=False)
        mod = _import_module()

        with pytest.raises(ValueError, match="FERNET_ENCRYPTION_KEY"):
            mod.encrypt_api_key(_PLAINTEXT)

    def test_value_error_when_key_empty(self, monkeypatch):
        """Raises ValueError when FERNET_ENCRYPTION_KEY is empty string."""
        monkeypatch.setenv("FERNET_ENCRYPTION_KEY", "")
        mod = _import_module()

        with pytest.raises(ValueError, match="FERNET_ENCRYPTION_KEY"):
            mod.encrypt_api_key(_PLAINTEXT)

    def test_value_error_on_decrypt_with_missing_key(self, monkeypatch):
        """decrypt_api_key also raises ValueError when key is missing."""
        monkeypatch.delenv("FERNET_ENCRYPTION_KEY", raising=False)
        mod = _import_module()

        with pytest.raises(ValueError, match="FERNET_ENCRYPTION_KEY"):
            mod.decrypt_api_key(b"garbage")

    def test_iv_randomness(self, monkeypatch):
        """Same plaintext produces different ciphertexts (IV/nonce randomness)."""
        monkeypatch.setenv("FERNET_ENCRYPTION_KEY", _TEST_FERNET_KEY)
        mod = _import_module()

        c1 = mod.encrypt_api_key(_PLAINTEXT)
        c2 = mod.encrypt_api_key(_PLAINTEXT)

        # Fernet includes a random IV, so two encryptions must differ
        assert c1 != c2

    def test_invalid_ciphertext(self, monkeypatch):
        """Decrypting garbage raises cryptography.fernet.InvalidToken."""
        monkeypatch.setenv("FERNET_ENCRYPTION_KEY", _TEST_FERNET_KEY)
        mod = _import_module()

        from cryptography.fernet import InvalidToken
        with pytest.raises(InvalidToken):
            mod.decrypt_api_key(b"not-a-valid-ciphertext")


# ---------------------------------------------------------------------------
# Module-level side-effect test
# ---------------------------------------------------------------------------


def test_module_importable_without_env_var():
    """Module can be imported without FERNET_ENCRYPTION_KEY (lazy init)."""
    # Deliberately NOT setting the env var — import must not raise
    from backend.services import encryption  # noqa: F811
    # No exception = pass
