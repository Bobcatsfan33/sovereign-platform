"""Tests for the per-pod mesh sidecar Envoy bootstrap (E3).

The sidecar terminates inbound mTLS (its SVID/bundle delivered over SDS when
enabled) and forwards plaintext to the co-located app on loopback, emitting
XFCC so the app's `require_bearer` sees the verified peer identity.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from sovereign.render import (
    _LOCAL_APP_CLUSTER,
    _OUTBOUND_CLUSTER,
    _SDS_CLUSTER_NAME,
    _SIDECAR_INBOUND_PORT,
    _SIDECAR_OUTBOUND_PORT,
    render_sidecar_bootstrap,
)


def _doc(service: str = "broker", app_port: int = 8080) -> dict[str, Any]:
    return yaml.safe_load(render_sidecar_bootstrap(service, app_port))


def _listener(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["static_resources"]["listeners"][0]


def _listener_named(doc: dict[str, Any], name: str) -> dict[str, Any]:
    return next(lst for lst in doc["static_resources"]["listeners"] if lst["name"] == name)


def _hcm(doc: dict[str, Any]) -> dict[str, Any]:
    return _listener(doc)["filter_chains"][0]["filters"][0]["typed_config"]


def test_sidecar_listens_on_mesh_inbound_port() -> None:
    doc = _doc()
    addr = _listener(doc)["address"]["socket_address"]
    assert addr["port_value"] == _SIDECAR_INBOUND_PORT


def test_sidecar_terminates_mtls_and_emits_xfcc() -> None:
    doc = _doc()
    chain = _listener(doc)["filter_chains"][0]
    tc = chain["transport_socket"]["typed_config"]
    assert tc["@type"].endswith("DownstreamTlsContext")
    assert tc["require_client_certificate"] is True
    hcm = _hcm(doc)
    assert hcm["forward_client_cert_details"] == "SANITIZE_SET"
    assert hcm["set_current_client_cert_details"] == {"uri": True}


def test_sidecar_forwards_to_local_app_on_loopback() -> None:
    doc = _doc(service="audit-service", app_port=8086)
    # Route targets the local_app cluster...
    vh = _hcm(doc)["route_config"]["virtual_hosts"][0]
    assert vh["routes"][0]["route"]["cluster"] == _LOCAL_APP_CLUSTER
    # ...which points at 127.0.0.1:<app_port> in plaintext (no transport socket).
    app = next(
        c for c in doc["static_resources"]["clusters"] if c["name"] == _LOCAL_APP_CLUSTER
    )
    assert "transport_socket" not in app
    sock = app["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]["address"][
        "socket_address"
    ]
    assert sock["address"] == "127.0.0.1"
    assert sock["port_value"] == 8086


def _chain_by_transport(doc: dict[str, Any], proto: str) -> dict[str, Any] | None:
    for chain in _listener(doc)["filter_chains"]:
        if chain.get("filter_chain_match", {}).get("transport_protocol") == proto:
            return chain
    return None


def test_sidecar_permissive_accepts_mtls_and_plaintext() -> None:
    """Default rollout posture: a tls_inspector splits traffic into an mTLS
    chain (cert + XFCC) and a plaintext chain (no cert), so a half-migrated
    mesh keeps serving not-yet-meshed callers."""
    doc = _doc()
    assert any("tls_inspector" in lf["name"] for lf in _listener(doc)["listener_filters"])
    tls_chain = _chain_by_transport(doc, "tls")
    raw_chain = _chain_by_transport(doc, "raw_buffer")
    assert tls_chain is not None and raw_chain is not None
    assert "transport_socket" in tls_chain
    assert tls_chain["filters"][0]["typed_config"]["forward_client_cert_details"] == "SANITIZE_SET"
    # Plaintext chain has no cert to terminate or forward.
    assert "transport_socket" not in raw_chain
    assert "forward_client_cert_details" not in raw_chain["filters"][0]["typed_config"]


def test_sidecar_strict_drops_plaintext_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "mesh_mtls_strict", True)
    settings_module.get_settings.cache_clear()
    try:
        doc = _doc()
        assert _chain_by_transport(doc, "raw_buffer") is None
        tls_chain = _chain_by_transport(doc, "tls")
        assert tls_chain is not None
        assert tls_chain["transport_socket"]["typed_config"]["require_client_certificate"] is True
    finally:
        settings_module.get_settings.cache_clear()


def test_sidecar_outbound_originates_mtls_to_original_dst() -> None:
    """The outbound listener captures redirected egress and tunnels it over
    mTLS to the original destination via an ORIGINAL_DST cluster."""
    doc = _doc()
    out = _listener_named(doc, "outbound_mtls")
    assert out["address"]["socket_address"]["port_value"] == _SIDECAR_OUTBOUND_PORT
    # original_dst listener filter keeps the real destination.
    assert any(
        "original_dst" in lf["name"] for lf in out["listener_filters"]
    )
    tcp = out["filter_chains"][0]["filters"][0]
    assert tcp["name"].endswith("tcp_proxy")
    assert tcp["typed_config"]["cluster"] == _OUTBOUND_CLUSTER

    cl = next(c for c in doc["static_resources"]["clusters"] if c["name"] == _OUTBOUND_CLUSTER)
    assert cl["type"] == "ORIGINAL_DST"
    assert cl["lb_policy"] == "CLUSTER_PROVIDED"
    assert cl["transport_socket"]["typed_config"]["@type"].endswith("UpstreamTlsContext")


def test_sidecar_file_mode_has_no_sds_cluster() -> None:
    doc = _doc()
    assert all(c["name"] != _SDS_CLUSTER_NAME for c in doc["static_resources"]["clusters"])
    common = _listener(doc)["filter_chains"][0]["transport_socket"]["typed_config"][
        "common_tls_context"
    ]
    assert "tls_certificates" in common


def test_sidecar_sds_mode_adds_spire_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "mesh_sds_enabled", True)
    settings_module.get_settings.cache_clear()
    try:
        doc = _doc()
        names = {c["name"] for c in doc["static_resources"]["clusters"]}
        assert _SDS_CLUSTER_NAME in names
        common = _listener(doc)["filter_chains"][0]["transport_socket"]["typed_config"][
            "common_tls_context"
        ]
        assert "tls_certificate_sds_secret_configs" in common
    finally:
        settings_module.get_settings.cache_clear()
