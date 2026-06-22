"""Encryption at rest for observra backends.

Provides Fernet symmetric encryption (cryptography package) with
PBKDF2-derived keys from passphrase material.

Key source priority:
    1. ABA_TELEMETRY_KEY environment variable (passphrase → PBKDF2 derivation)
    2. OS keyring via keyring.get_password() (optional dependency)
    3. None — encryption disabled

Usage::

    key = get_encryption_key()
    if key:
        provider = EncryptionProvider(key)
        ciphertext = provider.encrypt_line(plaintext)
        plaintext  = provider.decrypt_line(ciphertext)

Or use the module-level convenience functions::

    from observra.core.encryption import encrypt_line, decrypt_line
    ct = encrypt_line(key, "some text")
    pt = decrypt_line(key, ct)

Requires: pip install observra[encryption]
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Optional dependency guard ────────────────────────────────────────────────

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    Fernet = None  # type: ignore[assignment,misc]
    PBKDF2HMAC = None  # type: ignore[assignment]

# Fixed pepper mixed into the salt so that two different applications using
# ABA_TELEMETRY_KEY never share the same derived key space.
_SALT_PEPPER = b"observra-v1:"

# PBKDF2 iteration count (NIST SP 800-132 minimum; OWASP recommends 600k for
# SHA-256 in 2024 — we use 480k per the threat model T-33-01).
_PBKDF2_ITERATIONS = 480_000


def _derive_key_from_passphrase(passphrase: str) -> bytes:
    """Derive a 32-byte key from a passphrase using PBKDF2-HMAC-SHA256.

    The salt is a fixed pepper || SHA-256 of the passphrase itself. Because
    the passphrase IS the secret (like a password), salting with a hash of it
    prevents salt-reuse across different passphrases while keeping the derivation
    deterministic (no stored salt needed).

    Args:
        passphrase: User-provided passphrase string.

    Returns:
        32-byte derived key suitable for Fernet (after base64url-encoding).

    Raises:
        RuntimeError: If cryptography package is not installed.
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed. Run: pip install observra[encryption]")

    passphrase_bytes = passphrase.encode("utf-8")
    # Salt = pepper + SHA-256(passphrase) — deterministic, no stored salt needed.
    passphrase_hash = hashlib.sha256(passphrase_bytes).digest()
    salt = _SALT_PEPPER + passphrase_hash

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase_bytes)


class EncryptionProvider:
    """Fernet-based symmetric encryption provider.

    Each instance holds a Fernet key derived from the 32-byte raw key.
    The Fernet token format provides AES-128-CBC + HMAC-SHA256 authenticated
    encryption. Each token has a unique IV (nonce) — safe for encrypt-then-append.

    Args:
        key: 32-byte raw key (e.g., from get_encryption_key() or
             _derive_key_from_passphrase()).
    """

    def __init__(self, key: bytes) -> None:
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package not installed. Run: pip install observra[encryption]")
        if len(key) != 32:
            raise ValueError(f"Key must be 32 bytes, got {len(key)}")
        # Fernet expects a 32-byte key base64url-encoded with no padding stripped.
        fernet_key = base64.urlsafe_b64encode(key)
        self._fernet = Fernet(fernet_key)

    def encrypt_line(self, plaintext: str) -> str:
        """Encrypt a plaintext string and return a Fernet token (base64 string).

        The returned token contains no newlines and is safe to write as a single
        JSONL line. Each call produces a unique token (unique IV per Fernet spec).

        Args:
            plaintext: UTF-8 string to encrypt.

        Returns:
            Fernet token as a URL-safe base64 string.
        """
        token: bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("ascii")

    def decrypt_line(self, ciphertext: str) -> str:
        """Decrypt a Fernet token and return the original plaintext.

        Args:
            ciphertext: Fernet token string (from encrypt_line).

        Returns:
            Original plaintext string.

        Raises:
            ValueError: If the token is invalid, tampered, or was encrypted with
                a different key (raised by cryptography.fernet as a Fernet token error).
        """
        plaintext_bytes: bytes = self._fernet.decrypt(ciphertext.encode("ascii"))
        return plaintext_bytes.decode("utf-8")


def get_encryption_key() -> Optional[bytes]:
    """Retrieve the encryption key from the environment or OS keyring.

    Priority:
        1. ABA_TELEMETRY_KEY env var — treated as a passphrase and derived
           via PBKDF2-HMAC-SHA256 (480k iterations). Returns 32-byte key.
        2. OS keyring: keyring.get_password("observra", "encryption-key")
           — expects the stored value to also be a passphrase string.
        3. None — no key source available; caller should disable encryption.

    Returns:
        32-byte key bytes, or None if no key source is available.
    """
    if not _CRYPTO_AVAILABLE:
        logger.debug(
            "cryptography package not available; encryption disabled. Install: pip install observra[encryption]"
        )
        return None

    # 1. Environment variable (primary source per SEC-02)
    passphrase = os.environ.get("ABA_TELEMETRY_KEY")
    if passphrase:
        return _derive_key_from_passphrase(passphrase)

    # 2. OS keyring (optional fallback)
    try:
        import keyring  # type: ignore[import-untyped]

        stored = keyring.get_password("observra", "encryption-key")
        if stored:
            return _derive_key_from_passphrase(stored)
    except (ImportError, Exception) as exc:
        logger.debug("keyring unavailable or no entry found: %s", exc)

    return None


# ─── Module-level convenience functions ───────────────────────────────────────


def encrypt_line(key: bytes, text: str) -> str:
    """Encrypt a line using the given 32-byte key.

    Convenience wrapper creating a transient EncryptionProvider. Prefer
    creating a persistent EncryptionProvider instance when encrypting many lines.

    Args:
        key: 32-byte raw key bytes.
        text: Plaintext string to encrypt.

    Returns:
        Fernet token as ASCII string.
    """
    return EncryptionProvider(key).encrypt_line(text)


def decrypt_line(key: bytes, text: str) -> str:
    """Decrypt a Fernet token using the given 32-byte key.

    Args:
        key: 32-byte raw key bytes (same key used for encryption).
        text: Fernet token string.

    Returns:
        Original plaintext string.

    Raises:
        ValueError: If the token is invalid or key mismatches (raised by
            cryptography.fernet as a Fernet token error).
    """
    return EncryptionProvider(key).decrypt_line(text)
