"""Tests for audit event service-key signatures."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from sovereign.audit_signing import (
    canonical_signing_payload,
    reset_audit_signing_cache,
    sign_audit_event,
)
from sovereign.models import AuditEvent


def _private_key_pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")


def _configure_key(monkeypatch: pytest.MonkeyPatch, pem: str) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "audit_signature_key_id", "audit-key-1")
    monkeypatch.setattr(settings_module.Settings, "audit_signing_private_key_pem", pem)
    monkeypatch.setattr(settings_module.Settings, "require_audit_signing", True)
    settings_module.get_settings.cache_clear()
    reset_audit_signing_cache()


def test_sign_audit_event_adds_verifiable_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, _private_key_pem(key))
    event = AuditEvent(
        tenant_id="acme",
        actor="alice",
        action="policy.evaluated",
        resource="svc/demo",
        event_hash="abc123",
    )

    signed = sign_audit_event(event)

    assert signed.signature_key_id == "audit-key-1"
    assert signed.signature
    key.public_key().verify(
        base64.b64decode(signed.signature),
        canonical_signing_payload(signed),
    )


def test_sign_audit_event_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, _private_key_pem(key))
    signed = sign_audit_event(AuditEvent(action="x", resource="y", event_hash="abc"))

    assert sign_audit_event(signed) is signed


def test_signing_required_without_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "audit_signature_key_id", "audit-key-1")
    monkeypatch.setattr(settings_module.Settings, "audit_signing_private_key_pem", "")
    monkeypatch.setattr(settings_module.Settings, "require_audit_signing", True)
    settings_module.get_settings.cache_clear()
    reset_audit_signing_cache()

    with pytest.raises(RuntimeError, match="audit signing is required"):
        sign_audit_event(AuditEvent(action="x", resource="y"))


def test_signing_disabled_without_key_returns_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "audit_signing_private_key_pem", "")
    monkeypatch.setattr(settings_module.Settings, "require_audit_signing", False)
    settings_module.get_settings.cache_clear()
    reset_audit_signing_cache()

    event = AuditEvent(action="x", resource="y")
    assert sign_audit_event(event) is event


# Keep imported Any available for old Python coverage/plugin combinations.
_ = Any
