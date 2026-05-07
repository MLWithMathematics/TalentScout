"""
data_management/encryption.py — Field-Level Encryption (GDPR Art. 32)

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) to encrypt
all PII fields before writing to disk. The key is generated once and stored
at data/.encryption_key with OS-level permission restriction (chmod 600).

GDPR Relevance:
    - Article 32: "appropriate technical measures" → encryption satisfies this
    - Pseudonymisation: internal ID is used in logs, not name/email
"""

import os
from pathlib import Path
from cryptography.fernet import Fernet
from config import KEY_PATH, DATA_DIR


def _generate_or_load_key() -> bytes:
    """
    Generate a new AES encryption key on first run, or reload the existing one.
    Key file is created with chmod 600 (owner read/write only) for security.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()

    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)

    # Restrict permissions: owner read/write only (Unix/macOS)
    try:
        os.chmod(KEY_PATH, 0o600)
    except AttributeError:
        pass  # Windows — skip chmod

    return key


class EncryptionManager:
    """
    Handles encryption and decryption of sensitive candidate fields.

    Usage:
        enc = EncryptionManager()
        enc.encrypt("john@example.com")   → opaque ciphertext string
        enc.decrypt(ciphertext)           → "john@example.com"
    """

    def __init__(self):
        key = _generate_or_load_key()
        self._cipher = Fernet(key)

    # ── Core encrypt/decrypt ─────────────────────────────────────────

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a UTF-8 string; returns a URL-safe base64 ciphertext string."""
        if not plaintext:
            return ""
        return self._cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a Fernet ciphertext string; returns original plaintext."""
        if not ciphertext:
            return ""
        try:
            return self._cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except Exception:
            return "[DECRYPTION_ERROR]"

    # ── Masking helpers (for UI display & audit logs — never store raw PII) ──

    def mask_email(self, email: str) -> str:
        """r***@gmail.com — safe to display in sidebar / logs."""
        if "@" not in email:
            return "***@***.***"
        local, domain = email.split("@", 1)
        return f"{local[0]}***@{domain}"

    def mask_phone(self, phone: str) -> str:
        """XXXXXXX1234 — shows only last 4 digits."""
        digits_only = "".join(c for c in phone if c.isdigit())
        if len(digits_only) > 4:
            return "X" * (len(digits_only) - 4) + digits_only[-4:]
        return "****"

    def mask_name(self, name: str) -> str:
        """John D. — shows first name + last initial only."""
        parts = name.strip().split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[-1][0]}."
        return f"{name[0]}***" if name else "***"
