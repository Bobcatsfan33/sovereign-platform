"""Tests for the SecretsProvider abstraction (Step 0.3)."""

from __future__ import annotations

import pytest
from moto import mock_aws
from sovereign.secrets import (
    AwsSecretsManagerProvider,
    AwsSsmParameterProvider,
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


def test_unknown_provider_fails_closed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    reset_secrets_provider()
    from sovereign import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "secrets_provider", "vault-not-registered")
    try:
        with pytest.raises(RuntimeError, match="unknown secrets provider"):
            get_secrets_provider()
    finally:
        reset_secrets_provider()
        settings_mod.get_settings.cache_clear()


@mock_aws
def test_aws_secrets_manager_provider_reads_secret() -> None:
    import boto3

    client = boto3.client("secretsmanager", region_name="us-east-1")
    client.create_secret(Name="sovereign/test/api-key", SecretString="secret-value")

    p = AwsSecretsManagerProvider(region_name="us-east-1", prefix="sovereign/test/")
    assert p.get("api-key") == "secret-value"
    with pytest.raises(SecretNotFoundError):
        p.get("missing")


@mock_aws
def test_aws_ssm_parameter_provider_reads_secure_string() -> None:
    import boto3

    client = boto3.client("ssm", region_name="us-east-1")
    client.put_parameter(
        Name="/sovereign/test/token",
        Value="token-value",
        Type="SecureString",
    )

    p = AwsSsmParameterProvider(region_name="us-east-1", prefix="/sovereign/test/")
    assert p.get("token") == "token-value"
    with pytest.raises(SecretNotFoundError):
        p.get("missing")


@mock_aws
def test_factory_selects_aws_secrets_manager(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import boto3
    from sovereign import settings as settings_mod

    reset_secrets_provider()
    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "secrets_provider", "aws-secrets-manager")
    monkeypatch.setattr(settings_mod.Settings, "secrets_prefix", "prod/")
    boto3.client("secretsmanager", region_name="us-east-1").create_secret(
        Name="prod/db-password",
        SecretString="pw",
    )
    try:
        provider = get_secrets_provider()
        assert isinstance(provider, AwsSecretsManagerProvider)
        assert provider.get("db-password") == "pw"
    finally:
        reset_secrets_provider()
        settings_mod.get_settings.cache_clear()
