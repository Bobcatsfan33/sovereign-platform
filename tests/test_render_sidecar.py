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
    _SDS_CLUSTER_NAME,
    _SIDECAR_INBOUND_PORT,
    render_sidecar_bootstrap,
)


def _doc(service: str = "broker", app_port: int = 8080) -> dict[str, Any]:
    return yaml.safe_load(render_sidecar_bootstrap(service, app_port))


def _listener(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["static_resources"]["listeners"][0]


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
