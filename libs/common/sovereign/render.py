"""Envoy bootstrap config renderer.

Builds an Envoy v3 bootstrap doc from a ServiceInstance and serialises
to YAML. Task 0.6 adds Pydantic validation against `envoy_v3.EnvoyBootstrap`
before returning, so a template bug (missing field, wrong type, empty
collection) fails loudly here instead of silently shipping a broken
config to S3 / a real Envoy host.
"""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import ValidationError

from .envoy_v3 import validate_bootstrap
from .models import ServiceInstance


class RenderValidationError(ValueError):
    """Raised when the renderer produces a doc that does not satisfy
    the Envoy v3 schema subset enforced by `validate_bootstrap`."""


def _build_doc(instance: ServiceInstance) -> dict[str, Any]:
    params = instance.parameters
    listeners: list[dict[str, Any]] = []
    for listener in params.listeners:
        domains = sorted({r.host for r in params.routes}) or ["*"]
        routes: list[dict[str, Any]] = [
            {"match": {"prefix": r.prefix}, "route": {"cluster": r.cluster}}
            for r in params.routes
        ] or [{"match": {"prefix": "/"}, "direct_response": {"status": 404}}]
        listeners.append(
            {
                "name": listener.name,
                "address": {
                    "socket_address": {"address": "0.0.0.0", "port_value": listener.port}
                },
                "filter_chains": [
                    {
                        "filters": [
                            {
                                "name": "envoy.filters.network.http_connection_manager",
                                "typed_config": {
                                    "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                                    "stat_prefix": f"{instance.instance_id}_{listener.name}",
                                    "route_config": {
                                        "name": f"{listener.name}_routes",
                                        "virtual_hosts": [
                                            {
                                                "name": "service_routes",
                                                "domains": domains,
                                                "routes": routes,
                                            }
                                        ],
                                    },
                                    "http_filters": [
                                        {
                                            "name": "envoy.filters.http.router",
                                            "typed_config": {
                                                "@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"
                                            },
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                ],
            }
        )

    clusters: list[dict[str, Any]] = []
    for cluster in params.clusters:
        clusters.append(
            {
                "name": cluster.name,
                "connect_timeout": "2s",
                "type": "STRICT_DNS",
                "load_assignment": {
                    "cluster_name": cluster.name,
                    "endpoints": [
                        {
                            "lb_endpoints": [
                                {
                                    "endpoint": {
                                        "address": {
                                            "socket_address": {
                                                "address": ep.split(":")[0],
                                                "port_value": int(ep.split(":")[1]),
                                            }
                                        }
                                    }
                                }
                                for ep in cluster.endpoints
                            ]
                        }
                    ],
                },
            }
        )

    return {
        "static_resources": {"listeners": listeners, "clusters": clusters},
        "admin": {
            "access_log_path": "/tmp/admin_access.log",
            "address": {
                "socket_address": {"address": "0.0.0.0", "port_value": 9901}
            },
        },
    }


def render_envoy(instance: ServiceInstance) -> str:
    """Render the Envoy v3 bootstrap for `instance` and return YAML.

    Validates the assembled doc against the EnvoyBootstrap pydantic model
    before serialising. Raises RenderValidationError if validation fails."""
    doc = _build_doc(instance)
    try:
        validate_bootstrap(doc)
    except ValidationError as exc:
        raise RenderValidationError(
            f"rendered Envoy config failed schema validation: {exc}"
        ) from exc
    return yaml.safe_dump(doc, sort_keys=False)
