"""Tests for end-to-end protected task fields."""

import os

from cryptography.hazmat.primitives.asymmetric import ec

from custom_components.taskasquest.protected_fields import ProtectedFields


def test_encrypted_task_round_trip_and_update() -> None:
    """Encrypted create, read and update retain the same wrapped quest key."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    protected = ProtectedFields(private_key, private_key.public_key())
    encrypted, _ = protected.encrypt_task_write(
        {
            "title": "Secret quest",
            "description": "Secret details",
            "original_task": "Secret quest",
            "user_description": "Secret details",
        }
    )
    record = {"id": "task", **encrypted}

    decrypted = protected.decrypt_task_read(record)
    assert decrypted["title"] == "Secret quest"
    assert decrypted["description"] == "Secret details"

    update = protected.encrypt_task_update(
        record,
        {"title": "Updated quest", "description": None},
    )
    updated = protected.decrypt_task_read({**record, **update})
    assert updated["title"] == "Updated quest"
    assert updated["description"] is None


def test_unreadable_task_does_not_leak_ciphertext() -> None:
    """An invalid wrapped key produces a safe placeholder."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    protected = ProtectedFields(private_key, private_key.public_key())

    decrypted = protected.decrypt_task_read(
        {
            "crypto_version": 1,
            "quest_key_wrapped": os.urandom(32).hex(),
            "title_enc": "ciphertext",
        }
    )

    assert "fehlgeschlagen" in decrypted["title"]
