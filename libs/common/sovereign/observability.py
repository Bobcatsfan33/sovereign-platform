"""Small Prometheus text helpers for platform services.

The platform intentionally avoids a runtime dependency for these static
service gauges. Stateful counters can be layered behind the same endpoint
later without changing the route contract.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from fastapi import FastAPI, Response

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


def install_metrics_endpoint(
    app: FastAPI,
    *,
    service: str,
    extra_gauges: Callable[[], Mapping[str, int | float]] | None = None,
) -> None:
    def metrics() -> Response:
        gauges = extra_gauges() if extra_gauges is not None else None
        return service_metrics(service=service, extra_gauges=gauges)

    app.add_api_route("/metrics", metrics, methods=["GET"], include_in_schema=False)
