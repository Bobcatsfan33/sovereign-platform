"""Shared JSON problem-detail (RFC 7807) error handling.

The OSB spec asks brokers to return structured errors with a stable shape.
Pre-Phase-0 the apps returned ad-hoc detail strings or — worse — FastAPI's
default HTML 500 page on uncaught exceptions. This module installs a pair
of handlers on each FastAPI app:

  - HTTPException  -> problem detail JSON, preserving status + detail.
  - Exception      -> 500 problem detail JSON. The traceback is logged at
                      ERROR level but never leaked over the wire.

Caller pattern::

    from sovereign.errors import install_problem_detail_handlers
    app = FastAPI(...)
    install_problem_detail_handlers(app, service_name="broker")
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _problem(
    *,
    status: int,
    title: str,
    detail: str | Any = "",
    type_: str = "about:blank",
    service: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status,
        # If the caller passes a dict/list/etc as detail, preserve it
        # structurally so JSON-aware clients can parse it. Strings stay
        # strings; everything else is JSON-serialised as-is.
        "detail": detail if isinstance(detail, str | dict | list) else str(detail),
    }
    if service:
        body["service"] = service
    body.update(extra)
    return body


def install_problem_detail_handlers(app: FastAPI, *, service_name: str) -> None:
    """Register HTTPException, validation, and generic Exception handlers
    that return RFC 7807-style JSON. Idempotent — safe to call twice."""

    logger = logging.getLogger(f"sovereign.{service_name}.errors")

    @app.exception_handler(HTTPException)
    async def _http_exc(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_problem(
                status=exc.status_code,
                title=_title_for(exc.status_code),
                detail=exc.detail,
                service=service_name,
            ),
            headers=getattr(exc, "headers", None) or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_problem(
                status=422,
                title="unprocessable entity",
                detail="request body failed validation",
                service=service_name,
                errors=exc.errors(),
            ),
        )

    @app.exception_handler(Exception)
    async def _generic(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error in %s", service_name)
        return JSONResponse(
            status_code=500,
            content=_problem(
                status=500,
                title="internal server error",
                detail=str(exc),
                service=service_name,
            ),
        )


def _title_for(status: int) -> str:
    return {
        400: "bad request",
        401: "unauthorized",
        403: "forbidden",
        404: "not found",
        405: "method not allowed",
        409: "conflict",
        410: "gone",
        422: "unprocessable entity",
        429: "too many requests",
        500: "internal server error",
        502: "bad gateway",
        503: "service unavailable",
        504: "gateway timeout",
    }.get(status, f"HTTP {status}")
