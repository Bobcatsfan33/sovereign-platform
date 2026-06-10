"""Deep readiness checks (WS3 operability).

`/healthz` answers liveness — is the process up. `/readyz` answers readiness —
can this instance actually serve, i.e. are its dependencies reachable. k8s
gates traffic on readiness, so a service whose datastore or a downstream peer
is unreachable is pulled from rotation instead of serving errors.

A check returns a CheckResult; install_readiness aggregates them into a
`/readyz` that is 200 only when every check passes, with per-check JSON for
the operator. Checks may be sync or async and must never raise — a raising
check is reported as failed, not a 500.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Union

import httpx
from fastapi import FastAPI, Response

ReadinessCheck = Callable[[], Union["CheckResult", Awaitable["CheckResult"]]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


async def _run(check: ReadinessCheck) -> CheckResult:
    try:
        result = check()
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as exc:  # noqa: BLE001 — a readiness probe must fail soft
        return CheckResult(name=getattr(check, "_check_name", "check"), ok=False, detail=str(exc))


def callable_dependency(name: str, probe: Callable[[], object]) -> ReadinessCheck:
    """Wrap a sync probe that raises on failure (e.g. a DynamoDB describe) into
    a named readiness check."""

    def check() -> CheckResult:
        try:
            probe()
            return CheckResult(name, ok=True, detail="reachable")
        except Exception as exc:  # noqa: BLE001
            return CheckResult(name, ok=False, detail=str(exc))

    check._check_name = name  # type: ignore[attr-defined]
    return check


def http_dependency(name: str, url: str, *, timeout: float = 2.0) -> ReadinessCheck:
    """A downstream-service readiness check: GET `url`, healthy when it answers
    below 500 within `timeout`."""

    async def check() -> CheckResult:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
            return CheckResult(name, ok=response.status_code < 500, detail=f"{response.status_code}")
        except httpx.HTTPError as exc:
            return CheckResult(name, ok=False, detail=str(exc))

    check._check_name = name  # type: ignore[attr-defined]
    return check


def install_readiness(app: FastAPI, *, service: str, checks: list[ReadinessCheck]) -> None:
    async def readyz() -> Response:
        results = [await _run(c) for c in checks]
        ready = all(r.ok for r in results)
        body = json.dumps(
            {
                "service": service,
                "ready": ready,
                "checks": [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results],
            }
        )
        return Response(
            content=body,
            status_code=200 if ready else 503,
            media_type="application/json",
        )

    app.add_api_route("/readyz", readyz, methods=["GET"], include_in_schema=False)
