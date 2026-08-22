"""
Ed25519 keypair utilities.

Generate a keypair:  python -m backend.crypto.keys
The hex values go in your .env as ED25519_PRIVATE_KEY_HEX / ED25519_PUBLIC_KEY_HEX.
"""

import os
import nacl.signing
import nacl.encoding


def get_signing_key() -> nacl.signing.SigningKey:
    """Load the Ed25519 private key from the environment."""
    hex_key = os.getenv("ED25519_PRIVATE_KEY_HEX", "")
    if not hex_key:
        raise RuntimeError(
            "ED25519_PRIVATE_KEY_HEX not set. "
            "Run `python -m backend.crypto.keys` to generate a keypair."
        )
    return nacl.signing.SigningKey(bytes.fromhex(hex_key))


def get_verify_key() -> nacl.signing.VerifyKey:
    """Load the Ed25519 public key from the environment."""
    hex_key = os.getenv("ED25519_PUBLIC_KEY_HEX", "")
    if not hex_key:
        raise RuntimeError("ED25519_PUBLIC_KEY_HEX not set.")
    return nacl.signing.VerifyKey(bytes.fromhex(hex_key))


def sign_payload(payload_bytes: bytes) -> str:
    """Sign bytes with the server Ed25519 key. Returns 'ed25519:<hex_signature>'."""
    signing_key = get_signing_key()
    signed = signing_key.sign(payload_bytes)
    # signed.signature is the raw 64-byte signature
    return "ed25519:" + signed.signature.hex()


def verify_signature(payload_bytes: bytes, signature_str: str) -> bool:
    """
    Verify an 'ed25519:<hex>' signature against payload_bytes.
    Returns True if valid, False otherwise.
    """
    try:
        if not signature_str.startswith("ed25519:"):
            return False
        sig_hex = signature_str[len("ed25519:"):]
        sig_bytes = bytes.fromhex(sig_hex)
        verify_key = get_verify_key()
        verify_key.verify(payload_bytes, sig_bytes)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    # Generate and print a fresh keypair
    signing_key = nacl.signing.SigningKey.generate()
    verify_key  = signing_key.verify_key
    print("Add these to your .env file:")
    print(f"ED25519_PRIVATE_KEY_HEX={signing_key.encode().hex()}")
    print(f"ED25519_PUBLIC_KEY_HEX={verify_key.encode().hex()}")
