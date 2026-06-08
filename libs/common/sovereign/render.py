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


#: Where the mesh / deployment mounts this workload's TLS material. The
#: renderer references it by convention rather than embedding secrets, so
#: rotating certs is a deployment concern, not a re-render.
_MESH_TLS_DIR = "/etc/sovereign/tls"


def _common_tls_context() -> dict[str, Any]:
    """The shared CommonTlsContext both directions use: this workload's own
    cert/key (presented to peers) plus the CA bundle that verifies the other
    side. All three files are mounted by the mesh at `_MESH_TLS_DIR`, so cert
    rotation is a deployment concern rather than a re-render."""
    return {
        "tls_certificates": [
            {
                "certificate_chain": {"filename": f"{_MESH_TLS_DIR}/tls.crt"},
                "private_key": {"filename": f"{_MESH_TLS_DIR}/tls.key"},
            }
        ],
        "validation_context": {
            "trusted_ca": {"filename": f"{_MESH_TLS_DIR}/ca.crt"},
        },
    }


def _downstream_tls_transport_socket() -> dict[str, Any]:
    """A DownstreamTlsContext that terminates mTLS and REQUIRES a verified
    client certificate. Without this, `mtls_enabled` was a no-op boolean and
    the listener accepted plaintext. The validated peer identity is then
    forwarded upstream as XFCC (see `_xfcc_hcm_fields`)."""
    return {
        "name": "envoy.transport_sockets.tls",
        "typed_config": {
            "@type": (
                "type.googleapis.com/envoy.extensions.transport_sockets."
                "tls.v3.DownstreamTlsContext"
            ),
            "require_client_certificate": True,
            "common_tls_context": _common_tls_context(),
        },
    }


def _upstream_tls_transport_socket() -> dict[str, Any]:
    """An UpstreamTlsContext so the cluster ORIGINATES mTLS to its backends —
    presenting this workload's client cert and validating the upstream's
    server cert against the mesh CA. The mirror of the downstream socket:
    with both in place, east-west traffic is mutually authenticated in both
    directions, leaving no plaintext hop when `mtls_enabled` is set."""
    return {
        "name": "envoy.transport_sockets.tls",
        "typed_config": {
            "@type": (
                "type.googleapis.com/envoy.extensions.transport_sockets."
                "tls.v3.UpstreamTlsContext"
            ),
            "common_tls_context": _common_tls_context(),
        },
    }


def _xfcc_hcm_fields() -> dict[str, Any]:
    """HttpConnectionManager fields that make Envoy emit the verified peer
    identity as X-Forwarded-Client-Cert. `SANITIZE_SET` strips any client-
    supplied XFCC and rewrites it from the mTLS-verified certificate (so it
    cannot be spoofed on a direct path); `uri: true` includes the SPIFFE URI
    SAN — exactly what the services' `require_bearer` dependency parses."""
    return {
        "forward_client_cert_details": "SANITIZE_SET",
        "set_current_client_cert_details": {"uri": True},
    }


def _build_doc(instance: ServiceInstance) -> dict[str, Any]:
    params = instance.parameters
    listeners: list[dict[str, Any]] = []
    for listener in params.listeners:
        domains = sorted({r.host for r in params.routes}) or ["*"]
        routes: list[dict[str, Any]] = [
            {"match": {"prefix": r.prefix}, "route": {"cluster": r.cluster}}
            for r in params.routes
        ] or [{"match": {"prefix": "/"}, "direct_response": {"status": 404}}]
        hcm_typed_config: dict[str, Any] = {
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
            # When mTLS terminates here, forward the verified peer identity
            # upstream as XFCC so the sovereign services can authorize it.
            **(_xfcc_hcm_fields() if params.mtls_enabled else {}),
            "http_filters": [
                {
                    "name": "envoy.filters.http.router",
                    "typed_config": {
                        "@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"
                    },
                }
            ],
        }
        filter_chain: dict[str, Any] = {
            "filters": [
                {
                    "name": "envoy.filters.network.http_connection_manager",
                    "typed_config": hcm_typed_config,
                }
            ]
        }
        if params.mtls_enabled:
            filter_chain = {
                **filter_chain,
                "transport_socket": _downstream_tls_transport_socket(),
            }
        listeners.append(
            {
                "name": listener.name,
                "address": {
                    "socket_address": {"address": "0.0.0.0", "port_value": listener.port}
                },
                "filter_chains": [filter_chain],
            }
        )

    clusters: list[dict[str, Any]] = []
    for cluster in params.clusters:
        cluster_doc: dict[str, Any] = {
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
        if params.mtls_enabled:
            cluster_doc = {
                **cluster_doc,
                "transport_socket": _upstream_tls_transport_socket(),
            }
        clusters.append(cluster_doc)

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
