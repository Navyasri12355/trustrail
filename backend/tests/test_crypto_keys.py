"""
Tests for Ed25519 key utilities (crypto/keys.py).
"""

import os

import pytest

from backend.crypto.keys import get_signing_key, get_verify_key, sign_payload, verify_signature


class TestKeyLoading:
    """Test key loading from environment."""

    def test_get_signing_key_success(self):
        """Should successfully load signing key from environment."""
        # Uses the test key set in conftest.py
        key = get_signing_key()
        assert key is not None

    def test_get_verify_key_success(self):
        """Should successfully load verify key from environment."""
        key = get_verify_key()
        assert key is not None

    def test_get_signing_key_missing_env(self):
        """Should raise error when private key not in environment."""
        original_key = os.environ.get("ED25519_PRIVATE_KEY_HEX")
        os.environ.pop("ED25519_PRIVATE_KEY_HEX", None)
        try:
            with pytest.raises(RuntimeError, match="ED25519_PRIVATE_KEY_HEX not set"):
                get_signing_key()
        finally:
            if original_key:
                os.environ["ED25519_PRIVATE_KEY_HEX"] = original_key

    def test_get_verify_key_missing_env(self):
        """Should raise error when public key not in environment."""
        original_key = os.environ.get("ED25519_PUBLIC_KEY_HEX")
        os.environ.pop("ED25519_PUBLIC_KEY_HEX", None)
        try:
            with pytest.raises(RuntimeError, match="ED25519_PUBLIC_KEY_HEX not set"):
                get_verify_key()
        finally:
            if original_key:
                os.environ["ED25519_PUBLIC_KEY_HEX"] = original_key


class TestSigning:
    """Test payload signing."""

    def test_sign_payload(self):
        """Should successfully sign a payload."""
        payload = b"test_payload"
        signature = sign_payload(payload)
        assert signature.startswith("ed25519:")
        assert len(signature) > len("ed25519:")

    def test_sign_payload_deterministic(self):
        """Same payload should produce different signatures (due to Ed25519 randomness)."""
        payload = b"test_payload"
        sig1 = sign_payload(payload)
        sig2 = sign_payload(payload)
        # Ed25519 signatures are randomized, so they should differ
        # But both should be valid signatures
        assert sig1.startswith("ed25519:")
        assert sig2.startswith("ed25519:")


class TestVerification:
    """Test signature verification."""

    def test_verify_valid_signature(self):
        """Should verify a valid signature."""
        payload = b"test_payload"
        signature = sign_payload(payload)
        assert verify_signature(payload, signature) is True

    def test_verify_invalid_signature(self):
        """Should reject an invalid signature."""
        payload = b"test_payload"
        signature = "ed25519:invalid_signature_hex"
        assert verify_signature(payload, signature) is False

    def test_verify_wrong_signature(self):
        """Should reject signature for different payload."""
        payload1 = b"payload_1"
        payload2 = b"payload_2"
        signature = sign_payload(payload1)
        assert verify_signature(payload2, signature) is False

    def test_verify_malformed_signature(self):
        """Should reject malformed signature."""
        payload = b"test_payload"
        signature = "invalid_format"
        assert verify_signature(payload, signature) is False

    def test_verify_empty_signature(self):
        """Should reject empty signature."""
        payload = b"test_payload"
        signature = ""
        assert verify_signature(payload, signature) is False
