"""S-1: require_bearer verifies OIDC tokens and returns the real subject."""

from __future__ import annotations

from typing import Any

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sovereign.security import require_bearer


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    async def protected(identity: str = Depends(require_bearer)) -> dict[str, str]:
        return {"identity": identity}

    return app


class _FakeVerifier:
    def __init__(self, claims: dict[str, Any] | None = None, raises: bool = False) -> None:
        self._claims = claims or {}
        self._raises = raises

    def verify(self, token: str) -> dict[str, Any]:
        if self._raises:
            raise jwt.InvalidTokenError("bad token")
        return self._claims


def _enable_oidc(monkeypatch: pytest.MonkeyPatch, verifier: _FakeVerifier) -> None:
    from sovereign import idp
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "oidc_issuer_url", "https://idp.test")
    monkeypatch.setattr(settings_module.Settings, "oidc_audience", "sovereign")
    monkeypatch.setattr(settings_module.Settings, "require_oidc", True)
    monkeypatch.setattr(settings_module.Settings, "shared_bearer_auth_enabled", False)
    settings_module.get_settings.cache_clear()
    idp.set_oidc_verifier(verifier)  # type: ignore[arg-type]


def _cleanup() -> None:
    from sovereign import idp
    from sovereign import settings as settings_module

    idp.reset_oidc_verifier()
    settings_module.get_settings.cache_clear()


def test_valid_oidc_token_returns_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_oidc(monkeypatch, _FakeVerifier({"sub": "alice@agency.gov", "aud": "sovereign"}))
    try:
        r = TestClient(_app()).get("/protected", headers={"Authorization": "Bearer xyz"})
        assert r.status_code == 200
        assert r.json()["identity"] == "alice@agency.gov"  # real subject, not dev-user
    finally:
        _cleanup()


def test_missing_token_when_oidc_required_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_oidc(monkeypatch, _FakeVerifier({"sub": "x"}))
    try:
        r = TestClient(_app()).get("/protected")
        assert r.status_code == 401
        assert "OIDC bearer token required" in r.json()["detail"]
    finally:
        _cleanup()


def test_invalid_token_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_oidc(monkeypatch, _FakeVerifier(raises=True))
    try:
        r = TestClient(_app()).get("/protected", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401
        assert "invalid or expired token" in r.json()["detail"]
    finally:
        _cleanup()


def test_token_without_sub_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_oidc(monkeypatch, _FakeVerifier({"aud": "sovereign"}))
    try:
        r = TestClient(_app()).get("/protected", headers={"Authorization": "Bearer nosub"})
        assert r.status_code == 401
        assert "sub" in r.json()["detail"]
    finally:
        _cleanup()


def test_no_dev_user_string_in_libs() -> None:
    """The grep gate: the misleading 'dev-user' stub is gone from the library."""
    from pathlib import Path

    libs = Path(__file__).resolve().parent.parent / "libs"
    hits = [p for p in libs.rglob("*.py") if "dev-user" in p.read_text()]
    assert hits == [], f"'dev-user' still present in: {hits}"
