"""Tests for the HashiCorp Vault secrets backend (WS5 multi-cloud)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sovereign import secrets as secrets_module
from sovereign.secrets import SecretNotFoundError, VaultSecretsProvider


class _Resp:
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._body = body or {}

    def json(self) -> dict[str, Any]:
        return self._body


def _kv2(value: str) -> dict[str, Any]:
    return {"data": {"data": {"value": value}}}


def test_reads_kv2_value(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> _Resp:
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        return _Resp(200, _kv2("s3cr3t"))

    monkeypatch.setattr(secrets_module.httpx, "get", fake_get)
    p = VaultSecretsProvider(addr="https://vault:8200/", token="tok", mount="secret", prefix="prod/")
    assert p.get("broker-password") == "s3cr3t"
    assert seen["url"] == "https://vault:8200/v1/secret/data/prod/broker-password"
    assert seen["headers"]["X-Vault-Token"] == "tok"


def test_missing_secret_404_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets_module.httpx, "get", lambda url, **k: _Resp(404))
    with pytest.raises(SecretNotFoundError):
        VaultSecretsProvider(addr="http://v", token="t").get("absent")


def test_missing_value_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        secrets_module.httpx, "get", lambda url, **k: _Resp(200, {"data": {"data": {}}})
    )
    with pytest.raises(SecretNotFoundError):
        VaultSecretsProvider(addr="http://v", token="t").get("no-value")


def test_transport_error_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def boom(url: str, **k: Any) -> _Resp:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(secrets_module.httpx, "get", boom)
    with pytest.raises(SecretNotFoundError):
        VaultSecretsProvider(addr="http://v", token="t").get("x")


def test_build_provider_selects_vault() -> None:
    s = SimpleNamespace(
        secrets_provider="vault",
        aws_region="us-east-1",
        secrets_prefix="prod/",
        secrets_ttl_seconds=0,
        vault_addr="http://vault:8200",
        vault_token="tok",
        vault_kv_mount="secret",
    )
    provider = secrets_module._build_provider(s)  # type: ignore[arg-type]
    assert isinstance(provider, VaultSecretsProvider)


def test_vault_with_ttl_is_wrapped_for_rotation() -> None:
    from sovereign.secrets import RotatingSecretsProvider

    s = SimpleNamespace(
        secrets_provider="vault",
        aws_region="us-east-1",
        secrets_prefix="",
        secrets_ttl_seconds=300,
        vault_addr="http://vault:8200",
        vault_token="tok",
        vault_kv_mount="secret",
    )
    provider = secrets_module._build_provider(s)  # type: ignore[arg-type]
    assert isinstance(provider, RotatingSecretsProvider)
