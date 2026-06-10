"""Tests for API version negotiation + deprecation lifecycle (WS5)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sovereign.apiversion import (
    API_VERSION_HEADER,
    CURRENT_API_VERSION,
    UnsupportedApiVersionError,
    install_api_versioning,
    resolve_api_version,
)


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    install_api_versioning(app)
    return app


def test_resolve_defaults_to_current() -> None:
    assert resolve_api_version(None).name == CURRENT_API_VERSION
    assert resolve_api_version("").name == CURRENT_API_VERSION


def test_resolve_unsupported_raises() -> None:
    with pytest.raises(UnsupportedApiVersionError):
        resolve_api_version("1999-01-01")


def test_response_echoes_resolved_version() -> None:
    r = TestClient(_app()).get("/ping")
    assert r.status_code == 200
    assert r.headers[API_VERSION_HEADER] == CURRENT_API_VERSION
    assert "Deprecation" not in r.headers


def test_deprecated_version_gets_sunset_headers() -> None:
    r = TestClient(_app()).get("/ping", headers={API_VERSION_HEADER: "2026-01-01"})
    assert r.status_code == 200
    assert r.headers[API_VERSION_HEADER] == "2026-01-01"
    assert r.headers["Deprecation"] == "true"
    assert r.headers["Sunset"] == "2026-12-31"


def test_unsupported_version_is_rejected() -> None:
    r = TestClient(_app()).get("/ping", headers={API_VERSION_HEADER: "1999-01-01"})
    assert r.status_code == 400
    assert "problem+json" in r.headers["content-type"]
    assert "not supported" in r.text
