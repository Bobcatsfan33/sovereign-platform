"""Small Prometheus text helpers for platform services.

The platform intentionally avoids a runtime dependency for these static
service gauges. Stateful counters can be layered behind the same endpoint
later without changing the route contract.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .metrics import REGISTRY
from .tracing import (
    current_trace_id,
    format_traceparent,
    new_span_id,
    new_trace_id,
    parse_traceparent,
)

_access_log = logging.getLogger("sovereign.access")

_METRIC_NAME_RE = re.compile(r"[^a-zA-Z0-9_:]")
_LABEL_NAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def _metric_name(name: str) -> str:
    return _METRIC_NAME_RE.sub("_", name)


def _label_name(name: str) -> str:
    return _LABEL_NAME_RE.sub("_", name)


def _label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def gauge(name: str, description: str, value: int | float, labels: Mapping[str, str]) -> str:
    label_text = ",".join(
        f'{_label_name(k)}="{_label_value(v)}"' for k, v in sorted(labels.items())
    )
    suffix = f"{{{label_text}}}" if label_text else ""
    metric = _metric_name(name)
    return f"# HELP {metric} {description}\n# TYPE {metric} gauge\n{metric}{suffix} {value}\n"


def service_metrics(
    *,
    service: str,
    healthy: bool = True,
    extra_gauges: Mapping[str, int | float] | None = None,
) -> Response:
    body = gauge(
        "sovereign_service_up",
        "Service liveness reported by the application process.",
        1 if healthy else 0,
        {"service": service},
    )
    for name, value in sorted((extra_gauges or {}).items()):
        body += gauge(
            f"sovereign_{name}",
            f"Sovereign Platform {name.replace('_', ' ')}.",
            value,
            {"service": service},
        )
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


def _route_label(request: Request) -> str:
    """The matched route's path template (low cardinality), e.g.
    /v2/service_instances/{instance_id} — falls back to the raw path."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Per-request RED metrics + W3C trace propagation + an access log line.

    Continues an inbound `traceparent` (or starts a new trace), binds the
    trace id for log correlation, records request count + duration, and
    echoes `traceparent` on the response so the trace flows to the next hop."""

    def __init__(self, app: ASGIApp, *, service: str) -> None:
        super().__init__(app)
        self._service = service
        self._requests = REGISTRY.counter(
            "sovereign_http_requests_total", "Total HTTP requests handled."
        )
        self._duration = REGISTRY.histogram(
            "sovereign_http_request_duration_seconds", "HTTP request duration in seconds."
        )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = parse_traceparent(request.headers.get("traceparent"))
        trace_id = incoming[0] if incoming else new_trace_id()
        span_id = new_span_id()
        token = current_trace_id.set(trace_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["traceparent"] = format_traceparent(trace_id, span_id)
            return response
        finally:
            duration = time.perf_counter() - start
            route = _route_label(request)
            self._requests.inc(
                {
                    "service": self._service,
                    "method": request.method,
                    "route": route,
                    "status": str(status),
                }
            )
            self._duration.observe(
                duration,
                {"service": self._service, "method": request.method, "route": route},
            )
            _access_log.info(
                "%s %s %s %.4fs trace=%s",
                request.method,
                route,
                status,
                duration,
                trace_id,
            )
            current_trace_id.reset(token)


def install_metrics_endpoint(
    app: FastAPI,
    *,
    service: str,
    extra_gauges: Callable[[], Mapping[str, int | float]] | None = None,
) -> None:
    app.add_middleware(RequestObservabilityMiddleware, service=service)

    def metrics() -> Response:
        gauges = extra_gauges() if extra_gauges is not None else None
        base = service_metrics(service=service, extra_gauges=gauges)
        body = bytes(base.body).decode() + REGISTRY.render()
        return Response(content=body, media_type=base.media_type)

    app.add_api_route("/metrics", metrics, methods=["GET"], include_in_schema=False)
