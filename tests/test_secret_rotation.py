"""Tests for automatic secret rotation (WS5)."""

from __future__ import annotations

import pytest
from sovereign.secrets import RotatingSecretsProvider, SecretsProvider


class _CountingBackend(SecretsProvider):
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    def get(self, name: str) -> str:
        self.calls += 1
        return self.value


def test_rotating_caches_within_ttl_then_refetches() -> None:
    now = [0.0]
    backend = _CountingBackend("v1")
    p = RotatingSecretsProvider(backend, ttl_seconds=10, clock=lambda: now[0])

    assert p.get("token") == "v1"
    backend.value = "v2"  # rotated in the backend
    assert p.get("token") == "v1"  # still cached
    assert backend.calls == 1

    now[0] = 11  # TTL elapsed
    assert p.get("token") == "v2"  # auto-refetched
    assert backend.calls == 2


def test_force_expire_picks_up_rotation_immediately() -> None:
    now = [0.0]
    backend = _CountingBackend("v1")
    p = RotatingSecretsProvider(backend, ttl_seconds=10_000, clock=lambda: now[0])

    assert p.get("token") == "v1"
    backend.value = "v2"
    p.force_expire()  # e.g. a rotation webhook fired
    assert p.get("token") == "v2"


def test_get_optional_works_through_rotation() -> None:
    from sovereign.secrets import SecretNotFoundError

    class _Missing(SecretsProvider):
        def get(self, name: str) -> str:
            raise SecretNotFoundError(name)

    p = RotatingSecretsProvider(_Missing(), ttl_seconds=10)
    assert p.get_optional("absent", "fallback") == "fallback"


class _MutableProvider:
    def __init__(self, data: dict[str, str]) -> None:
        self.data = data

    def get(self, name: str) -> str:
        from sovereign.secrets import SecretNotFoundError

        if name in self.data:
            return self.data[name]
        raise SecretNotFoundError(name)

    def get_optional(self, name: str, default: str | None = None) -> str | None:
        return self.data.get(name, default)


def test_refresh_picks_up_rotated_value_in_running_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rotation re-resolves into the already-cached Settings — no restart."""
    from sovereign import settings as settings_module
    from sovereign.secrets import reset_secrets_provider, set_secrets_provider

    backend = _MutableProvider({"broker-password": "rotated-1"})
    monkeypatch.setattr(settings_module.Settings, "env", "production")
    monkeypatch.setattr(settings_module.Settings, "secrets_provider", "aws-secrets-manager")
    monkeypatch.setattr(settings_module.Settings, "broker_password", "broker")
    monkeypatch.setattr(settings_module.Settings, "strict_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "require_oidc", False)
    monkeypatch.setattr(settings_module.Settings, "require_managed_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "require_audit_signing", False)
    monkeypatch.setattr(settings_module.Settings, "broker_trust_basic_auth", False)
    reset_secrets_provider()
    set_secrets_provider(backend)  # type: ignore[arg-type]
    settings_module.get_settings.cache_clear()
    try:
        s = settings_module.get_settings()
        assert s.broker_password == "rotated-1"

        backend.data["broker-password"] = "rotated-2"  # rotation happens
        refreshed = settings_module.refresh_managed_secrets()
        assert refreshed is s  # same cached instance, updated in place
        assert settings_module.get_settings().broker_password == "rotated-2"
    finally:
        reset_secrets_provider()
        settings_module.get_settings.cache_clear()
