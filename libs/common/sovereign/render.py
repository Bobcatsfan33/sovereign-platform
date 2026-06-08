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
from .settings import Settings, get_settings


class RenderValidationError(ValueError):
    """Raised when the renderer produces a doc that does not satisfy
    the Envoy v3 schema subset enforced by `validate_bootstrap`."""


#: Where the mesh / deployment mounts this workload's TLS material when SDS
#: is NOT used. The renderer references it by convention rather than embedding
#: secrets, so rotating certs is a deployment concern, not a re-render.
_MESH_TLS_DIR = "/etc/sovereign/tls"

#: Name of the synthetic cluster that points Envoy at the SPIRE agent's SDS
#: socket. Referenced by every SDS secret config and added to the bootstrap
#: once when SDS is enabled.
_SDS_CLUSTER_NAME = "spiffe_sds"


def _file_common_tls_context() -> dict[str, Any]:
    """Static-file CommonTlsContext: this workload's own cert/key plus the CA
    bundle, all mounted by the deployment at `_MESH_TLS_DIR`."""
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


def _sds_config() -> dict[str, Any]:
    """An SdsSecretConfig `sds_config` that fetches secrets over gRPC from the
    SPIRE agent (the `_SDS_CLUSTER_NAME` cluster, a UDS to the agent socket)."""
    return {
        "api_config_source": {
            "api_type": "GRPC",
            "transport_api_version": "V3",
            "grpc_services": [{"envoy_grpc": {"cluster_name": _SDS_CLUSTER_NAME}}],
        }
    }


def _sds_common_tls_context(s: Settings) -> dict[str, Any]:
    """SDS CommonTlsContext: the SVID is delivered by SPIRE under this
    workload's SPIFFE id, and the trust bundle under the trust-domain id.
    Both are fetched live over the agent socket, so they auto-rotate without
    a re-render or a pod restart."""
    return {
        "tls_certificate_sds_secret_configs": [
            {"name": s.asserted_workload_identity(), "sds_config": _sds_config()}
        ],
        "validation_context_sds_secret_config": {
            "name": f"spiffe://{s.mesh_trust_domain()}",
            "sds_config": _sds_config(),
        },
    }


def _common_tls_context() -> dict[str, Any]:
    """The shared CommonTlsContext both directions use. Switches between
    SPIRE SDS (short-lived, auto-rotated SVIDs) and static mounted files
    based on `MESH_SDS_ENABLED`."""
    s = get_settings()
    if s.mesh_sds_enabled:
        return _sds_common_tls_context(s)
    return _file_common_tls_context()


def _sds_cluster() -> dict[str, Any]:
    """The synthetic gRPC cluster that reaches the SPIRE agent's SDS API over
    its Unix socket. Added to the bootstrap once when SDS is enabled so every
    TLS context's `sds_config` can resolve `_SDS_CLUSTER_NAME`."""
    s = get_settings()
    return {
        "name": _SDS_CLUSTER_NAME,
        "type": "STATIC",
        "connect_timeout": "1s",
        "http2_protocol_options": {},
        "load_assignment": {
            "cluster_name": _SDS_CLUSTER_NAME,
            "endpoints": [
                {
                    "lb_endpoints": [
                        {
                            "endpoint": {
                                "address": {"pipe": {"path": s.mesh_sds_socket_path}}
                            }
                        }
                    ]
                }
            ],
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

    # When mTLS resolves its certs over SDS, every TLS context references the
    # SPIRE-agent cluster — add it once so those sds_configs resolve.
    if params.mtls_enabled and get_settings().mesh_sds_enabled:
        clusters.append(_sds_cluster())

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


#: Port the per-pod mesh sidecar listens on for inbound east-west traffic.
#: The service routes here; the sidecar terminates mTLS and forwards plaintext
#: to the co-located app on loopback.
_SIDECAR_INBOUND_PORT = 15006

#: Cluster name for the co-located application the sidecar fronts.
_LOCAL_APP_CLUSTER = "local_app"


def _sidecar_doc(service_name: str, app_port: int) -> dict[str, Any]:
    inbound_listener: dict[str, Any] = {
        "name": "inbound_mtls",
        "address": {
            "socket_address": {"address": "0.0.0.0", "port_value": _SIDECAR_INBOUND_PORT}
        },
        "filter_chains": [
            {
                # The sidecar is inherently mTLS — that is its whole job — so the
                # transport socket and XFCC forwarding are unconditional here,
                # unlike the tenant-LB path where they hang off `mtls_enabled`.
                "transport_socket": _downstream_tls_transport_socket(),
                "filters": [
                    {
                        "name": "envoy.filters.network.http_connection_manager",
                        "typed_config": {
                            "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                            "stat_prefix": f"{service_name}_inbound",
                            "route_config": {
                                "name": "inbound_routes",
                                "virtual_hosts": [
                                    {
                                        "name": "local_app",
                                        "domains": ["*"],
                                        "routes": [
                                            {
                                                "match": {"prefix": "/"},
                                                "route": {"cluster": _LOCAL_APP_CLUSTER},
                                            }
                                        ],
                                    }
                                ],
                            },
                            **_xfcc_hcm_fields(),
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
                ],
            }
        ],
    }
    # Loopback to the app is a trusted in-pod hop — plaintext, no transport socket.
    local_app_cluster: dict[str, Any] = {
        "name": _LOCAL_APP_CLUSTER,
        "connect_timeout": "2s",
        "type": "STATIC",
        "load_assignment": {
            "cluster_name": _LOCAL_APP_CLUSTER,
            "endpoints": [
                {
                    "lb_endpoints": [
                        {
                            "endpoint": {
                                "address": {
                                    "socket_address": {
                                        "address": "127.0.0.1",
                                        "port_value": app_port,
                                    }
                                }
                            }
                        }
                    ]
                }
            ],
        },
    }
    clusters = [local_app_cluster]
    if get_settings().mesh_sds_enabled:
        clusters.append(_sds_cluster())
    return {
        "static_resources": {"listeners": [inbound_listener], "clusters": clusters},
        "admin": {
            "access_log_path": "/tmp/admin_access.log",
            "address": {"socket_address": {"address": "127.0.0.1", "port_value": 9901}},
        },
    }


def render_sidecar_bootstrap(service_name: str, app_port: int) -> str:
    """Render the Envoy bootstrap (YAML) for a chassis service's per-pod mesh
    sidecar. The inbound listener terminates mTLS — fetching its SVID/bundle
    over SDS when `MESH_SDS_ENABLED` — and forwards decrypted HTTP to the
    co-located app on 127.0.0.1:`app_port`, emitting XFCC so the app's
    `require_bearer` sees the verified peer identity."""
    doc = _sidecar_doc(service_name, app_port)
    try:
        validate_bootstrap(doc)
    except ValidationError as exc:
        raise RenderValidationError(
            f"rendered sidecar config failed schema validation: {exc}"
        ) from exc
    return yaml.safe_dump(doc, sort_keys=False)
