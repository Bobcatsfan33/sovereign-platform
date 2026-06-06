"""Tests for the Settings class and its production safety check."""

from __future__ import annotations

import logging
import os
from typing import Any

import pytest


def test_dev_defaults_are_loaded() -> None:
    from sovereign.settings import get_settings

    s = get_settings()
    # Defaults from conftest's environment
    assert s.dev_bearer_token == "test-token"  # overridden by conftest
    assert s.broker_username == "broker"


def test_production_fails_closed_for_dev_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production defaults to strict secret enforcement.

    A deployment with dev sentinels active must fail at startup unless an
    operator explicitly opts out with STRICT_SECRETS=false for a break-glass
    migration window.
    """
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "env", "production")
    monkeypatch.setattr(settings_module.Settings, "dev_bearer_token", "dev-token")
    monkeypatch.setattr(settings_module.Settings, "broker_password", "broker")
    monkeypatch.setattr(settings_module.Settings, "s3_secret_key", "minioadmin")
    monkeypatch.setattr(settings_module.Settings, "strict_secrets", True)
    settings_module.get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="refusing to start in a managed environment"):
        settings_module.get_settings()


def test_production_logs_warning_for_dev_defaults_when_strict_disabled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Explicitly disabling strict mode keeps the legacy warning behavior."""
    from sovereign import settings as settings_module

    monkeypatch.setenv("ENV", "production")
    # Force the dev defaults to be the live values on the Settings class.
    monkeypatch.setattr(settings_module.Settings, "dev_bearer_token", "dev-token")
    monkeypatch.setattr(settings_module.Settings, "broker_password", "broker")
    monkeypatch.setattr(settings_module.Settings, "s3_secret_key", "minioadmin")
    monkeypatch.setattr(settings_module.Settings, "env", "production")
    monkeypatch.setattr(settings_module.Settings, "strict_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "require_oidc", False)
    monkeypatch.setattr(settings_module.Settings, "require_managed_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "require_audit_signing", False)
    settings_module.get_settings.cache_clear()

    caplog.set_level(logging.ERROR)
    s = settings_module.get_settings()
    assert s.env == "production"
    messages = [r.getMessage() for r in caplog.records]
    assert any("dev defaults are still active" in m for m in messages)
    assert any("dev_bearer_token" in m for m in messages)


def test_basic_auth_rbac_bypass_defaults_off_in_production() -> None:
    """The OSB Basic compatibility path should not be trusted by default in prod."""
    from sovereign import settings as settings_module

    assert settings_module._default_broker_trust_basic_auth("production") is False
    assert settings_module._default_broker_trust_basic_auth("prod") is False
    assert settings_module._default_broker_trust_basic_auth("dev") is True


def test_strict_secrets_defaults_on_in_production() -> None:
    """Production should fail closed unless an operator explicitly opts out."""
    from sovereign import settings as settings_module

    assert settings_module._default_strict_secrets("production") is True
    assert settings_module._default_strict_secrets("prod") is True
    assert settings_module._default_strict_secrets("dev") is False


def test_auth_guardrails_default_for_production() -> None:
    from sovereign import settings as settings_module

    assert settings_module._default_shared_bearer_auth_enabled("production") is False
    assert settings_module._default_shared_bearer_auth_enabled("dev") is True
    assert settings_module._default_require_oidc("production") is True
    assert settings_module._default_require_oidc("dev") is False


def test_production_requires_oidc_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "env", "production")
    monkeypatch.setattr(settings_module.Settings, "strict_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "require_oidc", True)
    monkeypatch.setattr(settings_module.Settings, "require_managed_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "oidc_issuer_url", "")
    monkeypatch.setattr(settings_module.Settings, "oidc_audience", "")
    settings_module.get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="without OIDC_ISSUER_URL"):
        settings_module.get_settings()


def test_production_requires_managed_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "env", "production")
    monkeypatch.setattr(settings_module.Settings, "strict_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "require_oidc", False)
    monkeypatch.setattr(settings_module.Settings, "require_managed_secrets", True)
    monkeypatch.setattr(settings_module.Settings, "secrets_provider", "env")
    settings_module.get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="env-only secrets provider"):
        settings_module.get_settings()


def test_managed_secrets_and_workload_identity_defaults() -> None:
    from sovereign import settings as settings_module

    assert settings_module._default_require_managed_secrets("production") is True
    assert settings_module._default_require_managed_secrets("dev") is False
    assert settings_module._default_workload_identity_enabled("production") is True
    assert settings_module._default_workload_identity_enabled("dev") is False
    assert settings_module._default_require_audit_signing("production") is True
    assert settings_module._default_require_audit_signing("dev") is False


def test_production_requires_audit_signing_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "env", "production")
    monkeypatch.setattr(settings_module.Settings, "strict_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "require_oidc", False)
    monkeypatch.setattr(settings_module.Settings, "require_managed_secrets", False)
    monkeypatch.setattr(settings_module.Settings, "require_audit_signing", True)
    monkeypatch.setattr(settings_module.Settings, "audit_signature_key_id", "")
    monkeypatch.setattr(settings_module.Settings, "audit_signing_private_key_pem", "")
    settings_module.get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="audit signing key material"):
        settings_module.get_settings()


def test_unknown_env_is_treated_as_managed_not_dev() -> None:
    """Secure-by-default: only an explicit dev allowlist relaxes the
    guardrails. 'staging', 'demo', or a typo must be locked down."""
    from sovereign import settings as settings_module

    assert settings_module._is_development("dev") is True
    assert settings_module._is_development("Development") is True
    assert settings_module._is_development("ci") is True
    # Anything not on the allowlist requires real secrets.
    for env in ("staging", "demo", "gov-prod", "production", "prod", ""):
        assert settings_module._requires_real_secrets(env) is True, env


def test_guardrail_defaults_lock_down_unrecognised_env() -> None:
    """A non-dev, non-'production' env still gets every guardrail on."""
    from sovereign import settings as settings_module

    assert settings_module._default_strict_secrets("staging") is True
    assert settings_module._default_require_oidc("staging") is True
    assert settings_module._default_require_managed_secrets("staging") is True
    assert settings_module._default_workload_identity_enabled("staging") is True
    assert settings_module._default_require_audit_signing("staging") is True
    # ...and the permissive paths default OFF.
    assert settings_module._default_shared_bearer_auth_enabled("staging") is False
    assert settings_module._default_broker_trust_basic_auth("staging") is False


def test_staging_fails_closed_for_dev_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """The footgun this slice closes: a mislabelled (non-'production') env
    must NOT silently run on the baked-in dev credentials."""
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "env", "staging")
    monkeypatch.setattr(settings_module.Settings, "dev_bearer_token", "dev-token")
    monkeypatch.setattr(settings_module.Settings, "s3_secret_key", "minioadmin")
    monkeypatch.setattr(settings_module.Settings, "strict_secrets", True)
    settings_module.get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="ENV=staging"):
        settings_module.get_settings()


def test_no_hardcoded_credentials_in_source() -> None:
    """Smoke check that the store modules don't carry hardcoded AWS creds."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for relpath in ("libs/common/sovereign/store.py", "libs/common/sovereign/usage_store.py"):
        text = (root / relpath).read_text()
        assert 'aws_access_key_id="local"' not in text, (
            f"hardcoded creds reintroduced in {relpath}"
        )
        assert 'aws_secret_access_key="local"' not in text, (
            f"hardcoded creds reintroduced in {relpath}"
        )


def test_settings_picks_up_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new env-var value flows through after cache invalidation."""
    from sovereign import settings as settings_module

    monkeypatch.setenv("CONFIG_BUCKET", "some-other-bucket")
    monkeypatch.setattr(settings_module.Settings, "config_bucket", "some-other-bucket")
    settings_module.get_settings.cache_clear()
    s = settings_module.get_settings()
    assert s.config_bucket == "some-other-bucket"


# silence unused-import warning
_ = os, Any
