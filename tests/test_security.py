"""Tests for the shared bearer-auth FastAPI dependency."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sovereign.security import require_bearer

from .conftest import AUTH_HEADER


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_bearer)])
    def protected() -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_missing_header_returns_401() -> None:
    client = TestClient(_app())
    r = client.get("/protected")
    assert r.status_code == 401
    assert r.json()["detail"] == "missing bearer token"
    assert "Bearer" in r.headers.get("WWW-Authenticate", "")


def test_wrong_scheme_returns_401() -> None:
    client = TestClient(_app())
    r = client.get("/protected", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_invalid_token_returns_403() -> None:
    client = TestClient(_app())
    r = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403
    assert r.json()["detail"] == "invalid token"


def test_valid_token_returns_200() -> None:
    client = TestClient(_app())
    r = client.get("/protected", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json() == {"ok": "yes"}


def test_shared_bearer_disabled_returns_503(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "shared_bearer_auth_enabled", False)
    settings_module.get_settings.cache_clear()

    client = TestClient(_app())
    r = client.get("/protected", headers=AUTH_HEADER)
    assert r.status_code == 503
    assert "shared bearer auth is disabled" in r.json()["detail"]
