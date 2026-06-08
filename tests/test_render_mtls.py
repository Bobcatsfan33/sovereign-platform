"""Tests for mTLS termination + XFCC forwarding in the Envoy renderer (E2).

These assert the deployment-side half of the mesh-mTLS story: when an
instance is provisioned with `mtls_enabled`, the rendered Envoy listener
terminates mTLS (requiring a client cert) and forwards the verified peer
identity as XFCC — the header the services' `require_bearer` consumes.
"""

from __future__ import annotations

from typing import Any

import pytest
from sovereign.models import ProvisionRequest, ServiceInstance
from sovereign.render import _MESH_TLS_DIR, _SDS_CLUSTER_NAME, _build_doc, render_envoy


def _instance(*, mtls: bool) -> ServiceInstance:
    req = ProvisionRequest(
        service_id="sovereign-envoy-lb",
        plan_id="standard-regional",
        parameters={
            "mtls_enabled": mtls,
            "routes": [{"host": "app.local", "prefix": "/", "cluster": "app"}],
            "clusters": [{"name": "app", "endpoints": ["127.0.0.1:3000"]}],
        },
    )
    return ServiceInstance(instance_id="demo", **req.model_dump())


def _filter_chain(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["static_resources"]["listeners"][0]["filter_chains"][0]


def _hcm(doc: dict[str, Any]) -> dict[str, Any]:
    return _filter_chain(doc)["filters"][0]["typed_config"]


def _cluster(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["static_resources"]["clusters"][0]


def test_plaintext_listener_has_no_tls_or_xfcc() -> None:
    """Default (mtls_enabled=False) is unchanged: no transport socket, no
    client-cert forwarding, and no upstream TLS on clusters."""
    doc = _build_doc(_instance(mtls=False))
    assert "transport_socket" not in _filter_chain(doc)
    assert "transport_socket" not in _cluster(doc)
    hcm = _hcm(doc)
    assert "forward_client_cert_details" not in hcm
    assert "set_current_client_cert_details" not in hcm


def test_mtls_listener_terminates_and_requires_client_cert() -> None:
    doc = _build_doc(_instance(mtls=True))
    ts = _filter_chain(doc)["transport_socket"]
    assert ts["name"] == "envoy.transport_sockets.tls"
    tc = ts["typed_config"]
    assert tc["@type"].endswith("DownstreamTlsContext")
    assert tc["require_client_certificate"] is True
    # Cert material is referenced by the mesh-mounted convention path.
    common = tc["common_tls_context"]
    assert common["tls_certificates"][0]["private_key"]["filename"].startswith(_MESH_TLS_DIR)
    assert common["validation_context"]["trusted_ca"]["filename"] == f"{_MESH_TLS_DIR}/ca.crt"


def test_mtls_listener_forwards_xfcc_uri() -> None:
    """The HCM must emit XFCC with SANITIZE_SET (strip client-supplied copies)
    and include the URI SAN — exactly what parse_xfcc_identity reads."""
    hcm = _hcm(_build_doc(_instance(mtls=True)))
    assert hcm["forward_client_cert_details"] == "SANITIZE_SET"
    assert hcm["set_current_client_cert_details"] == {"uri": True}


def test_mtls_cluster_originates_upstream_tls() -> None:
    """The mirror of downstream termination: when mTLS is on, each cluster
    presents this workload's client cert to its backends (UpstreamTlsContext)
    so the upstream hop is mutually authenticated, not plaintext."""
    tc = _cluster(_build_doc(_instance(mtls=True)))["transport_socket"]["typed_config"]
    assert tc["@type"].endswith("UpstreamTlsContext")
    common = tc["common_tls_context"]
    assert common["tls_certificates"][0]["certificate_chain"]["filename"] == f"{_MESH_TLS_DIR}/tls.crt"
    assert common["validation_context"]["trusted_ca"]["filename"] == f"{_MESH_TLS_DIR}/ca.crt"


def test_mtls_doc_passes_schema_validation() -> None:
    """render_envoy validates the assembled doc; the mTLS additions must
    satisfy validate_bootstrap and survive YAML serialisation."""
    rendered = render_envoy(_instance(mtls=True))
    assert "DownstreamTlsContext" in rendered
    assert "UpstreamTlsContext" in rendered
    assert "SANITIZE_SET" in rendered


def test_xfcc_forwarding_feeds_require_bearer() -> None:
    """Cross-check the two halves of the mesh-mTLS story: the SAN type the
    renderer asks Envoy to emit is the one require_bearer's parser extracts."""
    from sovereign.mtls import parse_xfcc_identity

    hcm = _hcm(_build_doc(_instance(mtls=True)))
    assert hcm["set_current_client_cert_details"].get("uri") is True
    # Envoy emits XFCC as `...;URI=<san>` when uri=True; that is what the
    # inbound dependency parses back into the peer identity.
    sample = "Hash=abc;URI=spiffe://sovereign/broker"
    assert parse_xfcc_identity(sample) == "spiffe://sovereign/broker"


# ── E3: SDS / SPIRE cert delivery ──────────────────────────────────────


def _enable_sds(monkeypatch: pytest.MonkeyPatch, *, service_name: str = "broker") -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "mesh_sds_enabled", True)
    monkeypatch.setattr(settings_module.Settings, "service_name", service_name)
    settings_module.get_settings.cache_clear()


def test_file_mode_is_default_when_sds_disabled() -> None:
    """Without SDS, the TLS context uses static mounted files and no SDS
    cluster is added."""
    doc = _build_doc(_instance(mtls=True))
    common = _filter_chain(doc)["transport_socket"]["typed_config"]["common_tls_context"]
    assert "tls_certificates" in common
    assert "tls_certificate_sds_secret_configs" not in common
    assert all(c["name"] != _SDS_CLUSTER_NAME for c in doc["static_resources"]["clusters"])


def test_sds_mode_delivers_svid_and_bundle_over_spire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With SDS enabled, both directions fetch the SVID (under this workload's
    SPIFFE id) and the trust bundle (under the trust-domain id) from SPIRE,
    and a single spiffe_sds cluster reaches the agent socket over a UDS."""
    from sovereign import settings as settings_module

    _enable_sds(monkeypatch, service_name="broker")
    try:
        doc = _build_doc(_instance(mtls=True))
        for socket_tc in (
            _filter_chain(doc)["transport_socket"]["typed_config"],
            _cluster(doc)["transport_socket"]["typed_config"],
        ):
            common = socket_tc["common_tls_context"]
            assert "tls_certificates" not in common
            svid = common["tls_certificate_sds_secret_configs"][0]
            assert svid["name"] == "spiffe://sovereign/broker"
            assert (
                svid["sds_config"]["api_config_source"]["grpc_services"][0][
                    "envoy_grpc"
                ]["cluster_name"]
                == _SDS_CLUSTER_NAME
            )
            assert (
                common["validation_context_sds_secret_config"]["name"]
                == "spiffe://sovereign"
            )
        sds_clusters = [
            c for c in doc["static_resources"]["clusters"] if c["name"] == _SDS_CLUSTER_NAME
        ]
        assert len(sds_clusters) == 1
        ep = sds_clusters[0]["load_assignment"]["endpoints"][0]["lb_endpoints"][0]
        assert ep["endpoint"]["address"]["pipe"]["path"] == "/run/spire/sockets/agent.sock"
    finally:
        settings_module.get_settings.cache_clear()


def test_sds_doc_passes_schema_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDS additions (incl. the UDS pipe address) must satisfy
    validate_bootstrap and survive YAML serialisation."""
    from sovereign import settings as settings_module

    _enable_sds(monkeypatch)
    try:
        rendered = render_envoy(_instance(mtls=True))
        assert "tls_certificate_sds_secret_configs" in rendered
        assert "/run/spire/sockets/agent.sock" in rendered
    finally:
        settings_module.get_settings.cache_clear()
