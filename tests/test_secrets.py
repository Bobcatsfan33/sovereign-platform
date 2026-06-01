"""Tests for the SecretsProvider abstraction (Step 0.3)."""

from __future__ import annotations

import pytest
from sovereign.secrets import (
    EnvSecretsProvider,
    SecretNotFoundError,
    get_secrets_provider,
    reset_secrets_provider,
    set_secrets_provider,
)


def test_env_provider_reads_prefixed_var(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SOVEREIGN_SECRET_GITHUB_PAT", "ghp_xyz")
    p = EnvSecretsProvider()
    assert p.get("github-pat") == "ghp_xyz"
    assert p.get("github.pat") == "ghp_xyz"
    assert p.get("GITHUB_PAT") == "ghp_xyz"


def test_env_provider_missing_raises() -> None:
    p = EnvSecretsProvider()
    with pytest.raises(SecretNotFoundError):
        p.get("definitely-absent-secret")


def test_get_optional_returns_default() -> None:
    p = EnvSecretsProvider()
    assert p.get_optional("absent", "fallback") == "fallback"
    assert p.get_optional("absent") is None


def test_set_and_get_provider_round_trip() -> None:
    reset_secrets_provider()
    try:
        custom = EnvSecretsProvider()
        set_secrets_provider(custom)
        assert get_secrets_provider() is custom
    finally:
        reset_secrets_provider()


def test_default_provider_is_env() -> None:
    reset_secrets_provider()
    try:
        assert isinstance(get_secrets_provider(), EnvSecretsProvider)
    finally:
        reset_secrets_provider()


def test_unknown_provider_falls_back_to_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    reset_secrets_provider()
    from sovereign import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "secrets_provider", "vault-not-registered")
    try:
        # Falls back to env rather than crashing or leaking.
        assert isinstance(get_secrets_provider(), EnvSecretsProvider)
    finally:
        reset_secrets_provider()
        settings_mod.get_settings.cache_clear()
