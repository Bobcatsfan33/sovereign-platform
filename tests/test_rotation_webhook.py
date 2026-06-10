"""Tests for the secret-rotation webhook (WS5)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sovereign.rotation import install_rotation_webhook

from .conftest import AUTH_HEADER


def _app() -> FastAPI:
    app = FastAPI()
    install_rotation_webhook(app)
    return app


def test_refresh_requires_auth() -> None:
    r = TestClient(_app()).post("/admin/secrets/refresh")
    assert r.status_code == 401


def test_authenticated_refresh_triggers_reresolution() -> None:
    r = TestClient(_app()).post("/admin/secrets/refresh", headers=AUTH_HEADER)
    assert r.status_code == 200
    body = r.json()
    assert body["refreshed"] is True
    assert "provider" in body  # never leaks values, only which provider
