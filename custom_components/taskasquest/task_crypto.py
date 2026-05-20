"""Task as Quest zero-knowledge task crypto helpers."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HKDF_INFO = b"taq-qk-wrap-v1"
ENC_FIELDS = ("title", "description", "original_task", "user_description")


class TaskCryptoError(Exception):
    """Raised when Task as Quest crypto setup or operations fail."""


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _aes_gcm_decrypt(key: bytes, packed_b64: str) -> bytes:
    packed = _b64decode(packed_b64)
    if len(packed) <= 12:
        raise TaskCryptoError("Invalid encrypted payload")
    return AESGCM(key).decrypt(packed[:12], packed[12:], None)


def _aes_gcm_encrypt(key: bytes, plain: bytes) -> str:
    iv = os.urandom(12)
    cipher = AESGCM(key).encrypt(iv, plain, None)
    return _b64encode(iv + cipher)


def recovery_code_hash(recovery_code: str) -> str:
    """Return the app-compatible SHA-256/Base64 hash of a recovery code."""
    return _b64encode(hashlib.sha256(recovery_code.encode()).digest())


def verify_recovery_code(recovery_code: str, expected_hash: str | None) -> bool:
    """Return whether a recovery code matches the stored user hash."""
    if not recovery_code or not expected_hash:
        return False
    return recovery_code_hash(recovery_code.strip()) == expected_hash


def _derive_wrap_key(
    private_key: ec.EllipticCurvePrivateKey,
    public_key: ec.EllipticCurvePublicKey,
) -> bytes:
    shared = private_key.exchange(ec.ECDH(), public_key)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"",
        info=HKDF_INFO,
    ).derive(shared)


@dataclass(slots=True)
class TaskCrypto:
    """Encrypt and decrypt Task as Quest task fields."""

    master_key: bytes
    private_key: ec.EllipticCurvePrivateKey
    public_key: ec.EllipticCurvePublicKey

    @classmethod
    def from_user_record(cls, user_record: dict[str, Any], recovery_code: str) -> TaskCrypto:
        """Build crypto state from a PocketBase user record and recovery code."""
        if not verify_recovery_code(
            recovery_code,
            user_record.get("recovery_code_hash"),
        ):
            raise TaskCryptoError("Invalid recovery code")

        master_key = _b64decode(recovery_code.strip())
        if len(master_key) != 32:
            raise TaskCryptoError("Invalid recovery code length")

        priv_wrapped = user_record.get("priv_key_wrapped")
        pub_key = user_record.get("pub_key")
        if not priv_wrapped or not pub_key:
            raise TaskCryptoError("Missing crypto keys in user record")

        try:
            priv_der = _aes_gcm_decrypt(master_key, priv_wrapped)
            private_key = serialization.load_der_private_key(priv_der, password=None)
            public_key = serialization.load_der_public_key(_b64decode(pub_key))
        except (ValueError, InvalidTag) as err:
            raise TaskCryptoError("Could not unlock task crypto") from err

        if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
            public_key,
            ec.EllipticCurvePublicKey,
        ):
            raise TaskCryptoError("Unsupported crypto key type")

        return cls(master_key=master_key, private_key=private_key, public_key=public_key)

    def encrypt_task_write(self, plain: dict[str, str | None]) -> dict[str, Any]:
        """Encrypt app-sensitive task fields and wrap the quest key for the owner."""
        quest_key = os.urandom(32)
        payload: dict[str, Any] = {"crypto_version": 1}

        for field in ENC_FIELDS:
            value = plain.get(field)
            payload[f"{field}_enc"] = (
                None if value is None or value == "" else _aes_gcm_encrypt(quest_key, value.encode())
            )

        payload["quest_key_wrapped"] = self.wrap_quest_key(quest_key, self.public_key)
        return payload

    def decrypt_task_read(self, record: dict[str, Any]) -> dict[str, Any]:
        """Decrypt encrypted task fields for display in Home Assistant."""
        if record.get("crypto_version") != 1:
            return record

        wrapped = record.get("quest_key_wrapped")
        if not wrapped:
            return {
                **record,
                "title": "(kein Zugriff)",
                "description": None,
                "original_task": None,
                "user_description": None,
            }

        try:
            quest_key = self.unwrap_quest_key(wrapped)
        except TaskCryptoError:
            return {
                **record,
                "title": "(Entschluesselung fehlgeschlagen)",
                "description": None,
                "original_task": None,
                "user_description": None,
            }

        out = {**record}
        for field in ENC_FIELDS:
            encrypted = record.get(f"{field}_enc")
            if not encrypted:
                out[field] = None
                continue
            try:
                out[field] = _aes_gcm_decrypt(quest_key, encrypted).decode()
            except (UnicodeDecodeError, ValueError, InvalidTag):
                out[field] = "(Feld-Entschluesselung fehlgeschlagen)"
        return out

    def wrap_quest_key(
        self,
        quest_key: bytes,
        recipient_public_key: ec.EllipticCurvePublicKey,
    ) -> str:
        """Wrap a raw quest key for a recipient public key."""
        ephemeral_private_key = ec.generate_private_key(ec.SECP256R1())
        ephemeral_public_der = ephemeral_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        wrap_key = _derive_wrap_key(ephemeral_private_key, recipient_public_key)
        iv = os.urandom(12)
        cipher = AESGCM(wrap_key).encrypt(iv, quest_key, None)
        length = len(ephemeral_public_der).to_bytes(2, "big")
        return _b64encode(length + ephemeral_public_der + iv + cipher)

    def unwrap_quest_key(self, wrapped_b64: str) -> bytes:
        """Unwrap a task quest key with this user's private key."""
        packed = _b64decode(wrapped_b64)
        if len(packed) < 2:
            raise TaskCryptoError("Invalid wrapped quest key")

        pub_len = int.from_bytes(packed[:2], "big")
        pub_end = 2 + pub_len
        iv_end = pub_end + 12
        if len(packed) <= iv_end:
            raise TaskCryptoError("Invalid wrapped quest key")

        ephemeral_public = serialization.load_der_public_key(packed[2:pub_end])
        if not isinstance(ephemeral_public, ec.EllipticCurvePublicKey):
            raise TaskCryptoError("Unsupported ephemeral key type")

        wrap_key = _derive_wrap_key(self.private_key, ephemeral_public)
        try:
            return AESGCM(wrap_key).decrypt(packed[pub_end:iv_end], packed[iv_end:], None)
        except InvalidTag as err:
            raise TaskCryptoError("Could not unwrap quest key") from err
