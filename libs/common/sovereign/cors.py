"""Shared CORS helper for browser-facing services.

The portal SPA (Phase 4) runs in the user's browser and talks to the
broker on :8080 and the audit service on :8086. Browsers refuse to
issue those cross-origin requests without CORS headers, so the broker
and audit-service both register the middleware via `install_cors`.

Allow-list comes from settings.portal_origins (comma-separated). Empty
entries are filtered. We do NOT set `allow_credentials=True` because
the SPA sends bearer/basic tokens in the Authorization header (no
cookies), and `allow_credentials=True` requires explicit origin
matching that interacts badly with reverse proxies and load balancers.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .settings import get_settings


def install_cors(app: FastAPI) -> None:
    origins = [o.strip() for o in get_settings().portal_origins.split(",") if o.strip()]
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        allow_credentials=False,
        max_age=600,
    )
