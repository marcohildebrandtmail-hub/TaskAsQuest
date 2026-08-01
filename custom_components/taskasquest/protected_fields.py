"""Helpers for protected task fields."""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

HKDF_INFO = b"taq-qk-wrap-v1"
PBKDF2_ITERATIONS = 200_000
ENC_FIELDS = ("title", "description", "original_task", "user_description")


class ProtectedFieldsError(Exception):
    """Raised when protected task fields cannot be opened."""


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _aes_gcm_decrypt(key: bytes, packed_b64: str) -> bytes:
    packed = _b64decode(packed_b64)
    if len(packed) <= 12:
        raise ProtectedFieldsError("Invalid encrypted payload")
    return AESGCM(key).decrypt(packed[:12], packed[12:], None)


def _aes_gcm_encrypt(key: bytes, plain: bytes) -> str:
    iv = os.urandom(12)
    cipher = AESGCM(key).encrypt(iv, plain, None)
    return _b64encode(iv + cipher)


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
class ProtectedFields:
    """Encrypt and decrypt protected task fields."""

    private_key: ec.EllipticCurvePrivateKey
    public_key: ec.EllipticCurvePublicKey

    @classmethod
    def from_user_record(cls, user_record: dict[str, Any], password: str) -> ProtectedFields:
        """Unlock protected fields with the normal account password."""
        user_id = user_record.get("id")
        mk_wrapped = user_record.get("mk_wrapped")
        priv_wrapped = user_record.get("priv_key_wrapped")
        pub_key = user_record.get("pub_key")
        if not user_id or not mk_wrapped or not priv_wrapped or not pub_key:
            raise ProtectedFieldsError("Missing keys in account record")

        try:
            password_key = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=user_id.encode(),
                iterations=PBKDF2_ITERATIONS,
            ).derive(password.encode())
            master_key = _aes_gcm_decrypt(password_key, mk_wrapped)
            if len(master_key) != 32:
                raise ProtectedFieldsError("Invalid master key")
            priv_der = _aes_gcm_decrypt(master_key, priv_wrapped)
            private_key = serialization.load_der_private_key(priv_der, password=None)
            public_key = serialization.load_der_public_key(_b64decode(pub_key))
        except (TypeError, ValueError, InvalidTag, binascii.Error, UnicodeError) as err:
            raise ProtectedFieldsError("Could not unlock protected fields") from err

        if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
            public_key,
            ec.EllipticCurvePublicKey,
        ):
            raise ProtectedFieldsError("Unsupported key type")

        return cls(private_key=private_key, public_key=public_key)

    def encrypt_task_write(self, plain: dict[str, str | None]) -> tuple[dict[str, Any], bytes]:
        """Encrypt protected task fields."""
        quest_key = os.urandom(32)
        payload: dict[str, Any] = {"crypto_version": 1}

        for field in ENC_FIELDS:
            value = plain.get(field)
            payload[f"{field}_enc"] = (
                None
                if value is None or value == ""
                else _aes_gcm_encrypt(quest_key, value.encode())
            )

        payload["quest_key_wrapped"] = self.wrap_task_key(quest_key, self.public_key)
        return payload, quest_key

    def encrypt_task_update(
        self,
        record: dict[str, Any],
        plain: dict[str, str | None],
    ) -> dict[str, Any]:
        """Encrypt changed protected fields using an existing task key."""
        wrapped = record.get("quest_key_wrapped")
        if not wrapped:
            raise ProtectedFieldsError("Task does not contain a wrapped key")

        quest_key = self.unwrap_task_key(wrapped)
        payload: dict[str, Any] = {"crypto_version": 1}
        for field, value in plain.items():
            if field not in ENC_FIELDS:
                continue
            payload[f"{field}_enc"] = (
                None
                if value is None or value == ""
                else _aes_gcm_encrypt(quest_key, value.encode())
            )
        return payload

    def decrypt_task_read(self, record: dict[str, Any]) -> dict[str, Any]:
        """Decrypt protected task fields for display."""
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
            quest_key = self.unwrap_task_key(wrapped)
        except ProtectedFieldsError:
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
            except (
                UnicodeDecodeError,
                ValueError,
                InvalidTag,
                binascii.Error,
                ProtectedFieldsError,
            ):
                out[field] = "(Feld-Entschluesselung fehlgeschlagen)"
        return out

    def wrap_task_key(
        self,
        quest_key: bytes,
        recipient_public_key: ec.EllipticCurvePublicKey,
    ) -> str:
        """Wrap a raw task key for a recipient public key."""
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

    def wrap_task_key_for_b64_pub(self, quest_key: bytes, pub_key_b64: str) -> str:
        """Wrap a raw task key using a Base64-encoded DER public key."""
        try:
            pub_der = _b64decode(pub_key_b64)
            recipient_public_key = serialization.load_der_public_key(pub_der)
            if not isinstance(recipient_public_key, ec.EllipticCurvePublicKey):
                raise ProtectedFieldsError("Unsupported recipient key type")
            return self.wrap_task_key(quest_key, recipient_public_key)
        except (ValueError, TypeError, binascii.Error, ProtectedFieldsError) as err:
            raise ProtectedFieldsError("Could not wrap task key for recipient") from err

    def unwrap_task_key(self, wrapped_b64: str) -> bytes:
        """Unwrap a task key with this account's private key."""
        try:
            packed = _b64decode(wrapped_b64)
        except (ValueError, binascii.Error, UnicodeError) as err:
            raise ProtectedFieldsError("Invalid wrapped key") from err
        if len(packed) < 2:
            raise ProtectedFieldsError("Invalid wrapped key")

        pub_len = int.from_bytes(packed[:2], "big")
        pub_end = 2 + pub_len
        iv_end = pub_end + 12
        if len(packed) <= iv_end:
            raise ProtectedFieldsError("Invalid wrapped key")

        try:
            ephemeral_public = serialization.load_der_public_key(packed[2:pub_end])
        except ValueError as err:
            raise ProtectedFieldsError("Invalid ephemeral public key") from err
        if not isinstance(ephemeral_public, ec.EllipticCurvePublicKey):
            raise ProtectedFieldsError("Unsupported ephemeral key type")

        try:
            wrap_key = _derive_wrap_key(self.private_key, ephemeral_public)
            return AESGCM(wrap_key).decrypt(packed[pub_end:iv_end], packed[iv_end:], None)
        except (InvalidTag, ValueError) as err:
            raise ProtectedFieldsError("Could not unwrap key") from err
