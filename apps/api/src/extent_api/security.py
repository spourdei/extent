"""Small cryptographic primitives for OAuth state, credentials, and sessions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12
_VERSION_BYTES = 4


class CredentialDecryptionError(ValueError):
    """Raised without revealing whether a key, purpose, or ciphertext was wrong."""


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: bytes
    key_version: int


class CredentialKeyring:
    """Versioned AES-GCM keyring; the first configured key encrypts new values."""

    def __init__(self, keys: dict[int, bytes], current_version: int) -> None:
        if current_version not in keys:
            raise ValueError("current credential key version is missing")
        if any(len(key) != 32 for key in keys.values()):
            raise ValueError("credential encryption keys must decode to 32 bytes")
        self._keys = dict(keys)
        self.current_version = current_version

    @classmethod
    def from_config(cls, value: str) -> CredentialKeyring:
        """Parse newest-first ``version:base64url-key`` entries separated by commas."""

        keys: dict[int, bytes] = {}
        versions: list[int] = []
        for raw_entry in value.split(","):
            entry = raw_entry.strip()
            if not entry or ":" not in entry:
                raise ValueError("credential key entries must be version:base64url-key")
            raw_version, encoded_key = entry.split(":", 1)
            try:
                version = int(raw_version)
                padding = "=" * (-len(encoded_key) % 4)
                key = base64.b64decode(f"{encoded_key}{padding}", altchars=b"-_", validate=True)
            except (binascii.Error, ValueError, TypeError) as error:
                raise ValueError("credential key configuration is malformed") from error
            if version <= 0 or version in keys:
                raise ValueError("credential key versions must be unique positive integers")
            keys[version] = key
            versions.append(version)
        if not versions:
            raise ValueError("at least one credential encryption key is required")
        return cls(keys, versions[0])

    def encrypt(self, plaintext: str, *, purpose: str) -> EncryptedValue:
        if not plaintext:
            raise ValueError("cannot encrypt an empty credential")
        nonce = secrets.token_bytes(_NONCE_BYTES)
        key = self._keys[self.current_version]
        encrypted = AESGCM(key).encrypt(nonce, plaintext.encode(), purpose.encode())
        envelope = self.current_version.to_bytes(_VERSION_BYTES, "big") + nonce + encrypted
        return EncryptedValue(ciphertext=envelope, key_version=self.current_version)

    def decrypt(self, ciphertext: bytes, *, purpose: str) -> str:
        if len(ciphertext) <= _VERSION_BYTES + _NONCE_BYTES:
            raise CredentialDecryptionError("credential could not be decrypted")
        version = int.from_bytes(ciphertext[:_VERSION_BYTES], "big")
        key = self._keys.get(version)
        if key is None:
            raise CredentialDecryptionError("credential could not be decrypted")
        nonce_start = _VERSION_BYTES
        nonce_end = nonce_start + _NONCE_BYTES
        try:
            plaintext = AESGCM(key).decrypt(
                ciphertext[nonce_start:nonce_end],
                ciphertext[nonce_end:],
                purpose.encode(),
            )
            return plaintext.decode()
        except (InvalidTag, UnicodeDecodeError) as error:
            raise CredentialDecryptionError("credential could not be decrypted") from error


def random_urlsafe_token(byte_count: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(byte_count)).rstrip(b"=").decode()


def hash_secret(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()
