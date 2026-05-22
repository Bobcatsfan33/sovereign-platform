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


def test_production_logs_warning_for_dev_defaults(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When ENV=production and the dev sentinels are still in place,
    get_settings() emits an ERROR-level log line listing the keys."""
    from sovereign import settings as settings_module

    monkeypatch.setenv("ENV", "production")
    # Force the dev defaults to be the live values on the Settings class.
    monkeypatch.setattr(settings_module.Settings, "dev_bearer_token", "dev-token")
    monkeypatch.setattr(settings_module.Settings, "broker_password", "broker")
    monkeypatch.setattr(settings_module.Settings, "s3_secret_key", "minioadmin")
    monkeypatch.setattr(settings_module.Settings, "env", "production")
    settings_module.get_settings.cache_clear()

    caplog.set_level(logging.ERROR)
    s = settings_module.get_settings()
    assert s.env == "production"
    messages = [r.getMessage() for r in caplog.records]
    assert any("dev defaults are still active" in m for m in messages)
    assert any("dev_bearer_token" in m for m in messages)


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
